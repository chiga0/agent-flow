from __future__ import annotations

import io
import os
import socket
import subprocess
import tempfile
import unittest
import urllib.error
from http import cookies
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from runtime.cloud_agents_runtime.access import AccessManager, roles_allow, scopes_allow
from runtime.cloud_agents_runtime.adapters.base import RuntimeAdapter
from runtime.cloud_agents_runtime.adapters.fake import FakeAdapter
from runtime.cloud_agents_runtime.auth import AuthConfig, verify_password
from runtime.cloud_agents_runtime.budget import (
    BudgetConfig,
    CostManager,
    env_float as budget_env_float,
    numeric_metadata,
)
from runtime.cloud_agents_runtime.cleanup import (
    CleanupManager,
    CleanupPolicy,
    CleanupResult,
    directory_size,
    env_bool,
    env_nonnegative_int,
    is_relative_to,
    remove_workspace,
    terminal_created_at,
)
from runtime.cloud_agents_runtime.events import RuntimeEvent
from runtime.cloud_agents_runtime.executors import (
    ExecutorConfig,
    ExecutorRegistry,
    ManagedProcess,
    default_qwen_command,
    normalize_strategy,
    port_available,
    resource_float,
    resource_int,
)
from runtime.cloud_agents_runtime.models import (
    AccessProject,
    ApiToken,
    ExecutorLease,
    RunSpec,
    RunState,
    clean_channel,
    clean_notification_target,
    clean_principal_id,
)
from runtime.cloud_agents_runtime.notifications import (
    PermissionNotificationConfig,
    PermissionNotifier,
)
from runtime.cloud_agents_runtime.ops import BetaOpsConfig, OperationsManager
from runtime.cloud_agents_runtime.resources import (
    ResourceLimitConfig,
    ResourcePolicyResolver,
    ensure_dict,
    env_float,
    env_int,
    parse_memory_mb,
    parse_positive_int,
    resolve_float,
    resolve_int,
    resolve_timeout_seconds,
    validate_range,
)
from runtime.cloud_agents_runtime.review_gate import extract_json_object, parse_review_gate
from runtime.cloud_agents_runtime.store import RunStore
from runtime.cloud_agents_runtime.v2_control_plane import V2ControlPlane
from runtime.cloud_agents_runtime.workspace import (
    WorkspaceAllocator,
    is_git_worktree,
    source_path_for,
)


class AdditionalEdgeTest(unittest.TestCase):
    def test_resource_parsers_and_limits_reject_unsafe_values(self) -> None:
        with self.assertRaisesRegex(ValueError, "json object"):
            ensure_dict([], "sandbox")
        with self.assertRaisesRegex(ValueError, "positive number"):
            resolve_float({"cpu": "bad"}, ("cpu",), 1.0, "default")
        with self.assertRaisesRegex(ValueError, "positive integer"):
            resolve_int({"pids": object()}, ("pids",), 10, "default")

        self.assertEqual(
            resolve_timeout_seconds({"timeout": "5"}, None, 10),
            (5, "requested.timeout"),
        )
        self.assertEqual(
            resolve_timeout_seconds({}, "6", 10),
            (6, "run_spec.timeout_seconds"),
        )
        self.assertEqual(resolve_timeout_seconds({}, None, 10), (10, "default"))
        self.assertEqual(parse_memory_mb(512, "memory"), 512)
        self.assertEqual(parse_memory_mb(512.9, "memory"), 512)
        self.assertEqual(parse_memory_mb("1g", "memory"), 1024)
        self.assertEqual(parse_memory_mb("1kb", "memory"), 1)
        with self.assertRaisesRegex(ValueError, "memory in MB"):
            parse_memory_mb([], "memory")
        with self.assertRaisesRegex(ValueError, "memory in MB"):
            parse_memory_mb("many", "memory")
        with self.assertRaisesRegex(ValueError, "positive integer"):
            parse_positive_int("bad", "pids")
        with self.assertRaisesRegex(ValueError, "must be positive"):
            parse_positive_int(0, "pids")
        with self.assertRaisesRegex(ValueError, "must be positive"):
            validate_range("cpus", 0, 1)
        with self.assertRaisesRegex(ValueError, "exceeds worker maximum"):
            validate_range("cpus", 2, 1)

        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(env_int("MISSING", 7), 7)
            self.assertEqual(env_float("MISSING", 1.5), 1.5)
        with patch.dict(os.environ, {"BAD_INT": "bad", "BAD_FLOAT": "bad"}, clear=True):
            with self.assertRaisesRegex(ValueError, "positive integer"):
                env_int("BAD_INT", 1)
            with self.assertRaisesRegex(ValueError, "positive number"):
                env_float("BAD_FLOAT", 1.0)
        with patch.dict(os.environ, {"NEG_FLOAT": "-1"}, clear=True):
            with self.assertRaisesRegex(ValueError, "must be positive"):
                env_float("NEG_FLOAT", 1.0)

        resolver = ResourcePolicyResolver(ResourceLimitConfig(max_cpus=1.0))
        with self.assertRaisesRegex(ValueError, "json object"):
            resolver.resolve(RunSpec(sandbox=[]))  # type: ignore[arg-type]

    def test_cleanup_guardrails_cover_invalid_and_external_paths(self) -> None:
        self.assertIsNone(
            terminal_created_at([RuntimeEvent("run.started", "run", 1, {})])
        )
        self.assertIsNone(
            terminal_created_at(
                [RuntimeEvent("run.completed", "run", 1, {}, created_at="bad")]
            )
        )
        with patch.dict(
            os.environ,
            {
                "RUN_MANAGER_CLEANUP_ENABLED": "off",
                "RUN_MANAGER_WORKSPACE_RETENTION_SECONDS": "0",
                "RUN_MANAGER_ARTIFACT_RETENTION_SECONDS": "1",
                "RUN_MANAGER_CLEANUP_INTERVAL_SECONDS": "0",
            },
            clear=True,
        ):
            policy = CleanupPolicy.from_env()
        self.assertFalse(policy.enabled)
        self.assertEqual(policy.interval_seconds, 1)
        with patch.dict(os.environ, {}, clear=True):
            self.assertTrue(env_bool("MISSING", True))
            self.assertEqual(env_nonnegative_int("MISSING", 3), 3)
        with patch.dict(os.environ, {"FLAG": "yes", "BAD": "x", "NEG": "-1"}, clear=True):
            self.assertTrue(env_bool("FLAG", False))
            with self.assertRaisesRegex(ValueError, "non-negative integer"):
                env_nonnegative_int("BAD", 1)
            with self.assertRaisesRegex(ValueError, "must be non-negative"):
                env_nonnegative_int("NEG", 1)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            managed_root = root / "workspaces"
            managed_root.mkdir()
            store = MagicMock()
            store.run_dir.side_effect = lambda run_id: root / run_id
            manager = object.__new__(CleanupManager)
            manager.store = store
            manager.policy = CleanupPolicy(
                workspace_retention_seconds=0,
                artifact_retention_seconds=0,
            )
            manager.workspace_root = managed_root.resolve()
            result = CleanupResult()

            run = RunState.create(RunSpec(), run_id="run_cleanup")
            manager._cleanup_workspace(run, {"cleanup.workspace_deleted"}, result)
            manager._cleanup_workspace(run, set(), result)
            run.spec.metadata["workspace_allocation"] = {"isolated": False}
            manager._cleanup_workspace(run, set(), result)
            run.spec.metadata["workspace_allocation"] = {"isolated": True, "path": 1}
            manager._cleanup_workspace(run, set(), result)
            run.spec.metadata["workspace_allocation"] = {
                "isolated": True,
                "path": str(root / "outside"),
            }
            manager._cleanup_workspace(run, set(), result)
            self.assertEqual(result.warnings[0]["reason"], "workspace outside managed root")

            missing = managed_root / "missing"
            run.spec.metadata["workspace_allocation"] = {
                "isolated": True,
                "path": str(missing),
            }
            manager._cleanup_workspace(run, set(), result)
            workspace = managed_root / "run_cleanup"
            workspace.mkdir()
            (workspace / "file.txt").write_text("data", encoding="utf-8")
            run.spec.metadata["workspace_allocation"] = {
                "isolated": True,
                "path": str(workspace),
                "strategy": "directory_copy",
            }
            manager._cleanup_workspace(run, set(), result)
            self.assertFalse(workspace.exists())

            artifact_dir = root / run.run_id
            artifact_dir.mkdir()
            (artifact_dir / "result.json").write_text("{}", encoding="utf-8")
            self.assertEqual(directory_size(artifact_dir), 2)
            manager._cleanup_artifacts(run, set(), result)
            manager._cleanup_artifacts(run, {"cleanup.artifacts_deleted"}, result)
            manager._cleanup_artifacts(run, set(), result)
            self.assertFalse(is_relative_to(root, managed_root))

            fallback = managed_root / "fallback"
            fallback.mkdir()
            with patch(
                "runtime.cloud_agents_runtime.cleanup.subprocess.run",
                side_effect=subprocess.CalledProcessError(1, "git"),
            ):
                remove_workspace(
                    fallback,
                    {"strategy": "git_worktree", "source_path": str(root)},
                )
            self.assertFalse(fallback.exists())

    def test_access_auth_budget_models_and_adapter_boundaries(self) -> None:
        self.assertFalse(scopes_allow("runs:*", "runs:read"))
        self.assertFalse(scopes_allow([1], "runs:read"))
        self.assertFalse(roles_allow("owner", "runs:read"))
        self.assertIsNone(AuthConfig().bootstrap_email_value)
        self.assertFalse(AuthConfig().login_matches("owner", "secret"))
        self.assertIsNone(AuthConfig(login_user="owner").resolve_login_email("other"))
        self.assertFalse(verify_password("secret", "other$1$eA==$eA=="))
        with patch(
            "runtime.cloud_agents_runtime.auth.cookies.SimpleCookie",
            side_effect=cookies.CookieError("bad"),
        ):
            self.assertIsNone(AuthConfig().session_token("bad"))

        for method, args in (
            (RuntimeAdapter.capabilities, (object(),)),
            (RuntimeAdapter.start, (object(), object(), object())),
            (RuntimeAdapter.send_input, (object(), object(), "x", object())),
            (RuntimeAdapter.cancel, (object(), object(), None, object())),
        ):
            with self.assertRaises(NotImplementedError):
                method(*args)

        adapter = FakeAdapter(delay_seconds=0)
        adapter._cancelled.add("run_cancelled")
        fake_store = MagicMock()
        with patch.object(adapter, "_chunks", return_value=[]):
            adapter._complete_prompt("run_cancelled", 1, "x", {}, fake_store)
        fake_store.write_json.assert_not_called()

        self.assertEqual(AccessProject.from_payload({"id": "p"}).status, "active")
        with self.assertRaisesRegex(ValueError, "project status"):
            AccessProject.from_payload({"id": "p", "status": "deleted"})
        with self.assertRaisesRegex(ValueError, "scopes"):
            ApiToken.create(
                {"scopes": "runs:*"},
                plain_token="plain",
                default_principal="owner",
            )
        for function, value in (
            (clean_principal_id, ""),
            (clean_principal_id, "x\x00"),
            (clean_channel, ""),
            (clean_channel, "bad/channel"),
            (clean_notification_target, ""),
            (clean_notification_target, "x\x00"),
        ):
            with self.assertRaises(ValueError):
                function(value)
        lease = ExecutorLease("e", "r", "qwen", "shared", token="x")
        self.assertEqual(lease.to_dict()["token"], "configured")

        with tempfile.TemporaryDirectory() as tmp:
            store = RunStore(Path(tmp))
            access = AccessManager(store)
            self.assertEqual(
                access.principal_from_headers({"x-forwarded-user": "alice"}),
                "alice",
            )
            self.assertIsNone(access.authenticate_bearer("Bearer "))
            run = store.create_run(
                RunSpec(metadata={"estimated_cost_usd": 0.8}),
                run_id="run_cost",
            )
            self.assertEqual(run.run_id, "run_cost")
            warn_manager = CostManager(
                store,
                BudgetConfig(monthly_budget_usd=1.0, warning_ratio=0.8),
            )
            self.assertEqual(warn_manager.status()["status"], "warn")
            over_manager = CostManager(
                store,
                BudgetConfig(monthly_budget_usd=0.5),
            )
            self.assertEqual(over_manager.status()["status"], "over_budget")
            deny_manager = CostManager(
                store,
                BudgetConfig(
                    monthly_budget_usd=1.0,
                    per_run_budget_usd=0.5,
                    estimated_cost_per_run_usd=2.0,
                ),
            )
            quote = deny_manager.quote(RunSpec())
            self.assertFalse(quote["allowed"])
            self.assertEqual(len(quote["reasons"]), 2)
            with self.assertRaisesRegex(ValueError, "budget exceeded"):
                deny_manager.require_allowed(RunSpec())
            store.close()

        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(budget_env_float("MISSING", 1.0), 1.0)
        with patch.dict(os.environ, {"BAD": "bad", "NEG": "-2"}, clear=True):
            self.assertEqual(budget_env_float("BAD", 1.0), 1.0)
            self.assertEqual(budget_env_float("NEG", 1.0), 0.0)
        self.assertIsNone(numeric_metadata(True))
        self.assertEqual(numeric_metadata(-1), 0.0)
        self.assertEqual(numeric_metadata("1.5"), 1.5)
        self.assertIsNone(numeric_metadata("bad"))

    def test_executor_and_v2_error_paths(self) -> None:
        broken_handle = MagicMock()
        broken_handle.close.side_effect = RuntimeError("close")
        ManagedProcess(MagicMock(), broken_handle, broken_handle).close_logs()
        self.assertEqual(resource_float({"cpus": 0.5}, "cpus", 1.0), 0.5)
        self.assertEqual(resource_float({"cpus": True}, "cpus", 1.0), 1.0)
        self.assertEqual(resource_int({"pids": 3.9}, "pids", 1), 3)
        self.assertEqual(resource_int({"pids": True}, "pids", 2), 2)

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied:
            occupied.bind(("127.0.0.1", 0))
            occupied.listen(1)
            port = int(occupied.getsockname()[1])
            self.assertFalse(port_available("127.0.0.1", port))
            with tempfile.TemporaryDirectory() as tmp:
                store = RunStore(Path(tmp))
                registry = ExecutorRegistry(
                    store,
                    ExecutorConfig(port_start=port, port_end=port),
                )
                store.create_run(RunSpec(), run_id="run_exec")
                stored_lease = ExecutorLease(
                    "executor",
                    "run_exec",
                    "qwen",
                    "per_run_process",
                    status="running",
                )
                store.upsert_executor_lease(stored_lease)
                self.assertEqual(registry.capabilities()["counts"]["running"], 1)
                registry._reserved_ports.add(port)
                with self.assertRaisesRegex(RuntimeError, "no executor port"):
                    registry._allocate_port()
                self.assertIsNone(registry._terminate_process("missing", 0))

                running_process = MagicMock()
                running_process.poll.return_value = None
                registry._processes["executor"] = ManagedProcess(
                    running_process,
                    MagicMock(),
                    MagicMock(),
                )
                self.assertEqual(registry.reap_exited(), [])
                with patch.object(registry, "release_run") as release_run:
                    registry.shutdown()
                release_run.assert_called_once_with("run_exec", "runtime shutdown")
                registry._processes.clear()

                kill_process = MagicMock()
                kill_process.poll.return_value = None
                kill_process.wait.side_effect = [
                    subprocess.TimeoutExpired("qwen", 0),
                    0,
                ]
                kill_process.returncode = -9
                registry._processes["kill"] = ManagedProcess(
                    kill_process,
                    MagicMock(),
                    MagicMock(),
                )
                self.assertEqual(registry._terminate_process("kill", 0), -9)
                kill_process.kill.assert_called_once()

                process = MagicMock()
                process.poll.return_value = 2
                lease = ExecutorLease(
                    "executor",
                    "run",
                    "qwen",
                    "per_run_process",
                    base_url="http://127.0.0.1:1",
                )
                with self.assertRaisesRegex(RuntimeError, "exited early"):
                    registry._wait_until_ready(lease, process)
                process.poll.return_value = None
                error = urllib.error.HTTPError("url", 404, "not found", {}, None)
                with patch(
                    "runtime.cloud_agents_runtime.executors.urllib.request.urlopen",
                    side_effect=error,
                ):
                    registry._wait_until_ready(lease, process)
                server_error = urllib.error.HTTPError(
                    "url", 500, "server error", {}, None
                )
                with (
                    patch(
                        "runtime.cloud_agents_runtime.executors.urllib.request.urlopen",
                        side_effect=server_error,
                    ),
                    patch(
                        "runtime.cloud_agents_runtime.executors.time.monotonic",
                        side_effect=[0, 0, 21],
                    ),
                    patch("runtime.cloud_agents_runtime.executors.time.sleep"),
                ):
                    with self.assertRaisesRegex(RuntimeError, "did not become healthy"):
                        registry._wait_until_ready(lease, process)
                registry.config = ExecutorConfig(
                    strategy="container",
                    container_command_template="echo {run_id}",
                )
                self.assertEqual(
                    registry._command_for_run(
                        RunState.create(RunSpec(), run_id="run_command"),
                        Path(tmp),
                        {
                            "run_id": "run_command",
                            "host": "127.0.0.1",
                            "port": "1",
                            "executor_id": "executor",
                        },
                    ),
                    ["echo", "run_command"],
                )
                store.close()

        self.assertEqual(normalize_strategy("global"), "shared")
        self.assertIn("qwen serve", default_qwen_command())

        with tempfile.TemporaryDirectory() as tmp:
            control = V2ControlPlane(Path(tmp))
            with self.assertRaisesRegex(ValueError, "goal is required"):
                control.create_conversation({}, principal="owner")
            for callback in (
                lambda: control.get_conversation("missing", principal="owner"),
                lambda: control.conversation_for_task("missing", principal="owner"),
                lambda: control.update_conversation("missing", {}, principal="owner"),
                lambda: control.conversation_messages("missing", principal="owner"),
                lambda: control.append_conversation_message("missing", "x", principal="owner"),
                lambda: control.stop_conversation("missing", principal="owner"),
                lambda: control.get_approval("missing", principal="owner"),
                lambda: control.request_approval("missing", {}, principal="owner"),
            ):
                with self.assertRaises(KeyError):
                    callback()
            with self.assertRaisesRegex(ValueError, "message is required"):
                control.append_conversation_message("missing", " ", principal="owner")

            with patch.object(control, "create_task", side_effect=RuntimeError("boom")):
                with self.assertRaisesRegex(RuntimeError, "boom"):
                    control.create_conversation({"goal": "rollback"}, principal="owner")

            conversation = control.create_conversation(
                {"goal": "conversation edge"},
                principal="owner",
                idempotency_key="conversation-edge",
            )
            duplicate = control.create_conversation(
                {"goal": "conversation edge"},
                principal="owner",
                idempotency_key="conversation-edge",
            )
            self.assertEqual(duplicate["conversation_id"], conversation["conversation_id"])
            with self.assertRaisesRegex(ValueError, "title is required"):
                control.update_conversation(
                    conversation["conversation_id"],
                    {"title": "   "},
                    principal="owner",
                )
            self.assertEqual(
                control.wait_for_conversation_messages(
                    conversation["conversation_id"],
                    after=10**12,
                    timeout=0,
                    principal="owner",
                ),
                [],
            )
            control.close()
            self.assertEqual(
                control.wait_for_conversation_messages(
                    conversation["conversation_id"],
                    after=0,
                    timeout=0,
                    principal="owner",
                ),
                [],
            )

    def test_workspace_and_parser_regressions(self) -> None:
        self.assertIsNone(extract_json_object("```json\n{broken}\n``` trailing {bad}"))
        self.assertFalse(
            parse_review_gate({"decision": "pass", "findings": "bad"}).valid
        )
        self.assertFalse(
            parse_review_gate({"decision": "pass", "findings": ["bad"]}).valid
        )
        with patch.dict(os.environ, {"POSITIVE_FLOAT": "1.25"}, clear=True):
            self.assertEqual(env_float("POSITIVE_FLOAT", 1.0), 1.25)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            allocator = WorkspaceAllocator(root)
            shared = root / "shared"
            shared.mkdir()
            with patch.dict(
                os.environ,
                {
                    "QWEN_SERVE_CWD": str(shared),
                    "QWEN_EXECUTOR_STRATEGY": "shared",
                },
                clear=True,
            ):
                spec = RunSpec(adapter="qwen")
                allocation = allocator.prepare("run_shared", spec)
            self.assertEqual(allocation.strategy, "qwen_serve_shared")
            self.assertFalse(allocation.isolated)

            existing = root / "workspaces" / "run_existing"
            existing.mkdir(parents=True)
            with self.assertRaisesRegex(RuntimeError, "already exists"):
                allocator.prepare("run_existing", RunSpec())

            source = root / "source"
            source.mkdir()
            (source / "file.txt").write_text("content", encoding="utf-8")
            (source / ".git").mkdir()
            copied = allocator.prepare(
                "run_copy",
                RunSpec(workspace=str(source)),
            )
            self.assertEqual(copied.strategy, "directory_copy")
            self.assertTrue((Path(copied.path) / "file.txt").exists())
            self.assertFalse((Path(copied.path) / ".git").exists())
            self.assertEqual(source_path_for(RunSpec(repo=str(source))), source.resolve())
            self.assertFalse(is_git_worktree(root / "missing"))

            source_file = root / "source.txt"
            source_file.write_text("not a directory", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "not a directory"):
                allocator.prepare("run_file", RunSpec(workspace=str(source_file)))

    def test_cleanup_notifications_and_ops_terminal_edges(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = RunStore(root)
            store.create_run(RunSpec(), run_id="run_terminal_without_event")
            store.update_status("run_terminal_without_event", "completed")
            cleanup = CleanupManager(store, CleanupPolicy())
            self.assertEqual(cleanup.run_once().to_dict(), CleanupResult().to_dict())

            store.create_run(RunSpec(), run_id="run_failed")
            store.append_event("run_failed", "run.failed", {"reason": "smoke failure"})
            ops = OperationsManager(store, BetaOpsConfig(backup_retention_count=1))
            self.assertEqual(ops.metrics()["failures"]["by_reason"]["smoke failure"], 1)
            old_backup = ops.backup_dir / "old.tar.gz"
            new_backup = ops.backup_dir / "new.tar.gz"
            old_backup.write_bytes(b"old")
            new_backup.write_bytes(b"new")
            os.utime(old_backup, (1, 1))
            os.utime(new_backup, (2, 2))
            ops._prune_backups()
            self.assertFalse(old_backup.exists())
            self.assertTrue(new_backup.exists())
            store.close()

        run = RunState.create(RunSpec(), run_id="run_webhook_error")
        event = RuntimeEvent("permission.requested", run.run_id, 1, {})
        notifier = PermissionNotifier(
            PermissionNotificationConfig(
                channels=("webhook",),
                targets=("operator",),
                webhook_url="https://example.invalid/hook",
            )
        )
        notification = notifier.notifications_for(
            run=run,
            permission_id="permission_error",
            event=event,
        )[0]
        error = urllib.error.HTTPError(
            "https://example.invalid/hook",
            400,
            "bad request",
            {},
            io.BytesIO(b"denied"),
        )
        with patch(
            "runtime.cloud_agents_runtime.notifications.urllib.request.urlopen",
            side_effect=error,
        ):
            delivery = notifier.deliver(notification, run=run, event=event)
        self.assertEqual(delivery.status, "failed")
        self.assertEqual(delivery.error, "http 400: denied")


if __name__ == "__main__":
    unittest.main()
