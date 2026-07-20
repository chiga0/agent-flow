from __future__ import annotations

import tempfile
import threading
import time
import unittest
import urllib.parse
import os
import subprocess
from types import SimpleNamespace
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

from runtime.cloud_agents_runtime.adapters import FakeAdapter, RuntimeAdapter
from runtime.cloud_agents_runtime.models import RunState
from runtime.cloud_agents_runtime.store import RunStore
from runtime.cloud_agents_runtime.worker import (
    ActiveAgentContext,
    ControlPlaneClient,
    RemoteWorkerConfig,
    RemoteWorkerDaemon,
    host_resource_capacity,
    host_resource_metrics,
    parse_json_object,
    main as worker_main,
)
from runtime.tests.test_runtime_server import request_json, running_runtime


class RemoteWorkerDaemonTest(unittest.TestCase):
    def test_v2_control_loop_applies_cancel_and_permission_once(self) -> None:
        stop = threading.Event()
        process = SimpleNamespace(
            poll=lambda: None,
            terminate=Mock(),
        )
        context = ActiveAgentContext(
            assignment={
                "task_id": "task/unsafe",
                "agent_task_id": "agent/unsafe",
                "lease_token": "lease",
                "adapter": "codex",
            },
            process=process,
        )
        client = SimpleNamespace(
            v2_heartbeat=Mock(),
            v2_agent_event=Mock(),
        )

        def control(_worker_id: str) -> dict[str, object]:
            stop.set()
            return {
                "actions": [
                    "invalid",
                    {"agent_task_id": "other", "type": "cancel"},
                    {"agent_task_id": "agent/unsafe", "type": "cancel"},
                ],
                "permissions": [
                    "invalid",
                    {"agent_task_id": "other", "permission_id": "ignored"},
                    {"agent_task_id": "agent/unsafe", "permission_id": ""},
                    {
                        "agent_task_id": "agent/unsafe",
                        "permission_id": "permission-1",
                        "decision": {"allow": True},
                    },
                    {
                        "agent_task_id": "agent/unsafe",
                        "permission_id": "permission-1",
                    },
                ],
            }

        client.v2_control = control
        worker = RemoteWorkerDaemon(
            RemoteWorkerConfig(control_url="http://example.invalid", worker_id="worker"),
            client=client,
        )
        worker._v2_heartbeat_loop(stop, context)

        self.assertTrue(context.cancelled.is_set())
        process.terminate.assert_called_once_with()
        client.v2_agent_event.assert_called_once()
        self.assertEqual(context.applied_permissions, {"permission-1"})
        self.assertNotIn("SECRET_TOKEN", worker._sanitized_worker_env())
        with self.assertRaisesRegex(ValueError, "safe path segment"):
            worker._agent_workspace(context.assignment)

    def test_v2_helpers_cover_simulation_and_invalid_finish_action(self) -> None:
        client = ControlPlaneClient("http://example.invalid")
        with self.assertRaisesRegex(ValueError, "unsupported V2 agent action"):
            client.v2_finish_agent("worker", "agent", "pause", {})

        worker = RemoteWorkerDaemon(
            RemoteWorkerConfig(control_url="http://example.invalid", worker_id="worker"),
            client=SimpleNamespace(),
        )
        context = ActiveAgentContext(
            assignment={
                "task_id": "task",
                "agent_task_id": "agent",
                "lease_token": "lease",
                "adapter": "codex",
            }
        )
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"V2_ENABLE_REAL_CLI_ADAPTERS": "0"}
        ):
            summary, mode, exit_code = worker._run_v2_cli(
                context,
                {"goal": "simulate safely"},
                Path(tmp),
            )
        self.assertIn("simulate safely", summary)
        self.assertEqual((mode, exit_code), ("protocol-simulated", 0))

    def test_control_plane_client_builds_optional_artifact_payloads(self) -> None:
        client = ControlPlaneClient("http://example.invalid", token="secret")
        with patch.object(client, "request_json", return_value={}) as request:
            client.upload_artifact(
                "worker/a",
                "run/a",
                "events.jsonl",
                json_value={"ok": True},
                mode="append",
                chunk_index=2,
                final=True,
            )
            client.upload_artifact("worker/a", "run/a", "empty.txt")
            client.v2_heartbeat("worker/a", {"status": "active"})
            client.v2_claim("worker/a", {"capacity": 1})
            client.v2_control("worker/a")

        first_payload = request.call_args_list[0].kwargs["payload"]
        self.assertEqual(first_payload["json"], {"ok": True})
        self.assertEqual(first_payload["mode"], "append")
        self.assertEqual(first_payload["chunk_index"], 2)
        self.assertTrue(first_payload["final"])
        self.assertEqual(request.call_args_list[1].kwargs["payload"]["content"], "")

    def test_remote_worker_streams_v2_real_cli_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = root / "fake-codex"
            script.write_text(
                "#!/bin/sh\ncat >/dev/null\nprintf 'remote line one\\nremote line two\\n'\n",
                encoding="utf-8",
            )
            script.chmod(0o755)
            with running_runtime(
                artifact_root=root / "control", token="secret", worker_capacity=0
            ) as base_url:
                headers = {"authorization": "Bearer secret"}
                request_json(
                    f"{base_url}/v2/workers/codex-worker/heartbeat",
                    method="POST",
                    payload={"adapters": ["codex"]},
                    headers=headers,
                )
                task = request_json(
                    f"{base_url}/v2/tasks",
                    method="POST",
                    payload={"goal": "Execute Codex remotely", "adapter": "codex"},
                    headers=headers,
                )
                worker = RemoteWorkerDaemon(
                    RemoteWorkerConfig(
                        control_url=base_url,
                        token="secret",
                        worker_id="codex-worker",
                        heartbeat_interval_seconds=0.02,
                        artifact_root=root / "worker",
                    )
                )
                with patch.dict(
                    os.environ,
                    {
                        "V2_ENABLE_REAL_CLI_ADAPTERS": "1",
                        "V2_CODEX_CLI_COMMAND": str(script),
                    },
                ):
                    self.assertTrue(worker.run_once(wait=True))
                completed = request_json(
                    f"{base_url}/v2/tasks/{task['task_id']}", headers=headers
                )
                self.assertEqual(completed["execution_mode"], "real-cli")
                events = request_json(
                    f"{base_url}/v2/tasks/{task['task_id']}/events.json",
                    headers=headers,
                )["events"]
                messages = [event for event in events if event["type"] == "agent.message"]
                self.assertEqual(len(messages), 2)

    def test_remote_worker_completes_real_repository_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "projects" / "calculator"
            repo.mkdir(parents=True)
            (repo / "calculator.py").write_text(
                "def add(left, right):\n    return left + right\n", encoding="utf-8"
            )
            (repo / "test_calculator.py").write_text(
                "import unittest\n"
                "from calculator import add\n\n"
                "class CalculatorTest(unittest.TestCase):\n"
                "    def test_add(self):\n"
                "        self.assertEqual(add(2, 3), 5)\n\n"
                "if __name__ == '__main__':\n"
                "    unittest.main()\n",
                encoding="utf-8",
            )
            subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
            subprocess.run(
                ["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True
            )
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo),
                    "-c",
                    "user.name=test",
                    "-c",
                    "user.email=test@example.com",
                    "commit",
                    "-m",
                    "initial",
                ],
                check=True,
                capture_output=True,
            )
            initial_head = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            script = root / "fake-codex"
            script.write_text(
                "#!/bin/sh\n"
                "cat > agent-request.json\n"
                "printf 'def add(left, right):\\n    return left + right\\n\\n"
                "def subtract(left, right):\\n    return left - right\\n' "
                "> calculator.py\n"
                "printf '# Calculator\\n\\nSupports add and subtract.\\n' > README.md\n"
                "printf 'implemented calculator changes\\n'\n",
                encoding="utf-8",
            )
            script.chmod(0o755)

            with running_runtime(
                artifact_root=root / "control", token="secret", worker_capacity=0
            ) as base_url:
                headers = {"authorization": "Bearer secret"}
                request_json(
                    f"{base_url}/v2/workers/mac-worker/heartbeat",
                    method="POST",
                    payload={"kind": "remote-worker", "adapters": ["codex"]},
                    headers=headers,
                )
                goal = (
                    "Add subtraction support to the calculator, update its README, "
                    "preserve addition behavior, and run the full unit test suite."
                )
                task = request_json(
                    f"{base_url}/v2/tasks",
                    method="POST",
                    payload={
                        "goal": goal,
                        "mode": "single",
                        "adapter": "codex",
                        "workspace": {
                            "source_path": str(repo),
                            "ref": "HEAD",
                            "test_command": ["python3", "-m", "unittest", "-v"],
                        },
                    },
                    headers=headers,
                )
                worker = RemoteWorkerDaemon(
                    RemoteWorkerConfig(
                        control_url=base_url,
                        token="secret",
                        worker_id="mac-worker",
                        heartbeat_interval_seconds=0.02,
                        artifact_root=root / "worker",
                    )
                )
                with patch.dict(
                    os.environ,
                    {
                        "V2_ENABLE_REAL_CLI_ADAPTERS": "1",
                        "V2_CODEX_CLI_COMMAND": str(script),
                        "V2_WORKSPACE_ROOTS": str(repo.parent),
                    },
                ):
                    self.assertTrue(worker.run_once(wait=True))

                completed = request_json(
                    f"{base_url}/v2/tasks/{task['task_id']}", headers=headers
                )
                self.assertEqual(completed["status"], "completed")
                self.assertEqual(completed["plan"]["agent_tasks"][0]["goal"], goal)
                artifacts = request_json(
                    f"{base_url}/v2/tasks/{task['task_id']}/artifacts", headers=headers
                )["artifacts"]
                by_name = {artifact["name"]: artifact for artifact in artifacts}
                self.assertTrue(by_name["test_results"]["content"]["passed"])
                self.assertIn("README.md", by_name["git_patch"]["content"]["text"])
                self.assertTrue(by_name["git_commit"]["content"]["hash"])
                self.assertEqual(
                    subprocess.run(
                        ["git", "-C", str(repo), "rev-parse", "HEAD"],
                        check=True,
                        capture_output=True,
                        text=True,
                    ).stdout.strip(),
                    initial_head,
                )
                self.assertFalse((repo / "README.md").exists())

    def test_remote_worker_executes_v2_agent_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            control_root = Path(tmp) / "control"
            worker_root = Path(tmp) / "worker"
            with running_runtime(
                artifact_root=control_root,
                token="secret",
                worker_capacity=0,
            ) as base_url:
                headers = {"authorization": "Bearer secret"}
                request_json(
                    f"{base_url}/v2/workers/nas-worker/heartbeat",
                    method="POST",
                    payload={
                        "kind": "remote-worker",
                        "status": "active",
                        "adapters": ["fake"],
                        "lease_ttl_seconds": 30,
                    },
                    headers=headers,
                )
                task = request_json(
                    f"{base_url}/v2/tasks",
                    method="POST",
                    payload={"goal": "Verify a remote V2 worker", "adapter": "fake"},
                    headers=headers,
                )
                self.assertEqual(
                    task["metadata"]["dispatch"]["execution_unit_id"], "nas-worker"
                )
                self.assertEqual(task["status"], "queued")

                worker = RemoteWorkerDaemon(
                    RemoteWorkerConfig(
                        control_url=base_url,
                        token="secret",
                        worker_id="nas-worker",
                        heartbeat_interval_seconds=0.05,
                        artifact_root=worker_root,
                    )
                )
                self.assertTrue(worker.run_once(wait=True))
                completed = request_json(
                    f"{base_url}/v2/tasks/{task['task_id']}", headers=headers
                )
                self.assertEqual(completed["status"], "completed")
                self.assertEqual(
                    completed["result"]["artifacts"][0]["content"]["adapter"]["worker_id"],
                    "nas-worker",
                )
                events = request_json(
                    f"{base_url}/v2/tasks/{task['task_id']}/events.json", headers=headers
                )
                self.assertIn(
                    "agent_task.completed", {event["type"] for event in events["events"]}
                )
                self.assertTrue((worker_root / "v2" / task["task_id"]).is_dir())

    def test_remote_worker_daemon_once_executes_fake_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            control_root = Path(tmp) / "control"
            worker_root = Path(tmp) / "worker"
            with running_runtime(
                artifact_root=control_root,
                token="secret",
                worker_capacity=0,
            ) as base_url:
                headers = {"authorization": "Bearer secret"}
                run = request_json(
                    f"{base_url}/runs",
                    method="POST",
                    payload={"prompt": "hello from remote daemon", "adapter": "fake"},
                    headers=headers,
                )
                worker = RemoteWorkerDaemon(
                    RemoteWorkerConfig(
                        control_url=base_url,
                        token="secret",
                        worker_id="vps/a",
                        capacity=1,
                        lease_ttl_seconds=30,
                        heartbeat_interval_seconds=0.05,
                        run_wait_timeout_seconds=2,
                        artifact_root=worker_root,
                        metadata={
                            "region": "test-region",
                            "capabilities": {"features": ["custom-feature"]},
                        },
                    )
                )

                self.assertTrue(worker.run_once(wait=True))

                deadline = time.time() + 2
                current: dict[str, object] = {}
                while time.time() < deadline:
                    current = request_json(
                        f"{base_url}/runs/{run['run_id']}",
                        headers=headers,
                    )
                    if current["status"] == "completed":
                        break
                    time.sleep(0.02)

                self.assertEqual(current["status"], "completed")
                events = request_json(
                    f"{base_url}/runs/{run['run_id']}/events.json",
                    headers=headers,
                )
                event_types = [event["type"] for event in events["events"]]
                self.assertIn("adapter.run_id", event_types)
                self.assertIn("run.started", event_types)
                self.assertIn("run.completed", event_types)
                artifacts = request_json(
                    f"{base_url}/runs/{run['run_id']}/artifacts",
                    headers=headers,
                )
                artifact_names = {artifact["name"] for artifact in artifacts["artifacts"]}
                self.assertIn("final_1.json", artifact_names)
                self.assertIn("raw_events.jsonl", artifact_names)
                self.assertTrue((worker_root / run["run_id"] / "final_1.json").exists())
                raw_events = worker_root / run["run_id"] / "raw_events.jsonl"
                self.assertIn('"index": 1', raw_events.read_text(encoding="utf-8"))
                worker_path = urllib.parse.quote("vps/a", safe="")
                worker_state = request_json(f"{base_url}/workers/{worker_path}", headers=headers)
                self.assertEqual(worker_state["worker"]["metadata"]["region"], "test-region")
                self.assertIn(
                    "fake",
                    worker_state["worker"]["metadata"]["capabilities"]["adapters"],
                )
                self.assertIn(
                    "custom-feature",
                    worker_state["worker"]["metadata"]["capabilities"]["features"],
                )
                self.assertIn(
                    "claim",
                    worker_state["worker"]["metadata"]["capabilities"]["features"],
                )
                self.assertIn("metrics", worker_state["worker"]["metadata"])
                self.assertIn("resources", worker_state["worker"]["metadata"])

    def test_remote_worker_reports_host_resource_snapshot(self) -> None:
        capacity = host_resource_capacity()
        metrics = host_resource_metrics()
        self.assertGreaterEqual(capacity["cpus"], 1)
        self.assertIsInstance(metrics, dict)
        self.assertTrue(
            {
                "cpu_percent",
                "memory_percent",
                "disk_percent",
                "load_average",
                "swap_percent",
            }.intersection(metrics.keys())
        )

    def test_resource_metric_helpers_cover_edge_cases(self) -> None:
        with patch(
            "runtime.cloud_agents_runtime.worker.linux_meminfo_kb",
            return_value={
                "MemTotal": 2 * 1024 * 1024,
                "MemAvailable": 512 * 1024,
                "SwapTotal": 1024,
                "SwapFree": 256,
            },
        ):
            self.assertEqual(host_resource_capacity()["memory_gb"], 2)
            with (
                patch("runtime.cloud_agents_runtime.worker.os.cpu_count", return_value=2),
                patch(
                    "runtime.cloud_agents_runtime.worker.os.getloadavg",
                    return_value=(4.0, 0.0, 0.0),
                ),
                patch(
                    "runtime.cloud_agents_runtime.worker.shutil.disk_usage",
                    return_value=SimpleNamespace(total=100, used=75),
                ),
            ):
                metrics = host_resource_metrics()
        self.assertEqual(metrics["cpu_percent"], 100.0)
        self.assertEqual(metrics["memory_percent"], 75.0)
        self.assertEqual(metrics["swap_percent"], 75.0)
        self.assertEqual(metrics["disk_percent"], 75.0)

        with (
            patch(
                "runtime.cloud_agents_runtime.worker.os.getloadavg",
                side_effect=OSError("load unavailable"),
            ),
            patch(
                "runtime.cloud_agents_runtime.worker.shutil.disk_usage",
                side_effect=OSError("disk unavailable"),
            ),
            patch("runtime.cloud_agents_runtime.worker.linux_meminfo_kb", return_value={}),
        ):
            self.assertEqual(host_resource_metrics(), {})
        self.assertEqual(parse_json_object(None), {})
        with self.assertRaises(ValueError):
            parse_json_object("[]")

    def test_remote_worker_cli_help(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            worker_main(["--help"])
        self.assertEqual(ctx.exception.code, 0)

    def test_remote_worker_applies_control_plane_cancel(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            control_root = Path(tmp) / "control"
            with running_runtime(
                artifact_root=control_root,
                token="secret",
                worker_capacity=0,
            ) as base_url:
                headers = {"authorization": "Bearer secret"}
                prompt = " ".join(f"word-{index}" for index in range(220))
                run = request_json(
                    f"{base_url}/runs",
                    method="POST",
                    payload={"prompt": prompt, "adapter": "fake", "timeout_seconds": 5},
                    headers=headers,
                )
                worker = RemoteWorkerDaemon(
                    RemoteWorkerConfig(
                        control_url=base_url,
                        token="secret",
                        worker_id="vps-cancel",
                        capacity=1,
                        heartbeat_interval_seconds=0.05,
                        run_wait_timeout_seconds=5,
                    ),
                    adapters={"fake": FakeAdapter(delay_seconds=0.05)},
                )
                self.assertTrue(worker.run_once(wait=False))
                wait_for_status(base_url, run["run_id"], "running", headers)
                request_json(
                    f"{base_url}/runs/{run['run_id']}/cancel",
                    method="POST",
                    payload={"reason": "operator cancel"},
                    headers=headers,
                )
                cancelled = wait_for_status(base_url, run["run_id"], "cancelled", headers)
                self.assertEqual(cancelled["status"], "cancelled")
                events = request_json(
                    f"{base_url}/runs/{run['run_id']}/events.json",
                    headers=headers,
                )
                event_types = [event["type"] for event in events["events"]]
                self.assertIn("run.cancel_requested", event_types)
                self.assertIn("run.cancelled", event_types)

    def test_remote_worker_applies_permission_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            control_root = Path(tmp) / "control"
            with running_runtime(
                artifact_root=control_root,
                token="secret",
                worker_capacity=0,
            ) as base_url:
                headers = {"authorization": "Bearer secret"}
                run = request_json(
                    f"{base_url}/runs",
                    method="POST",
                    payload={"prompt": "needs approval", "adapter": "fake"},
                    headers=headers,
                )
                worker = RemoteWorkerDaemon(
                    RemoteWorkerConfig(
                        control_url=base_url,
                        token="secret",
                        worker_id="vps-permission",
                        capacity=1,
                        heartbeat_interval_seconds=0.05,
                        run_wait_timeout_seconds=5,
                    ),
                    adapters={"fake": PermissionAdapter()},
                )
                self.assertTrue(worker.run_once(wait=False))
                wait_for_event(base_url, run["run_id"], "permission.requested", headers)
                request_json(
                    f"{base_url}/runs/{run['run_id']}/permissions/perm-remote",
                    method="POST",
                    payload={
                        "decision": "approve",
                        "decided_by": "test",
                        "reason": "remote permission test",
                    },
                    headers=headers,
                )
                completed = wait_for_status(base_url, run["run_id"], "completed", headers)
                self.assertEqual(completed["status"], "completed")
                events = request_json(
                    f"{base_url}/runs/{run['run_id']}/events.json",
                    headers=headers,
                )
                event_types = [event["type"] for event in events["events"]]
                self.assertIn("permission.resolve_requested", event_types)
                self.assertIn("permission.resolved", event_types)


class PermissionAdapter(RuntimeAdapter):
    name = "fake"

    def capabilities(self) -> dict[str, Any]:
        return {"name": self.name, "features": ["permission"]}

    def start(self, run: RunState, store: RunStore) -> None:
        store.append_event(run.run_id, "run.started", {"adapter": self.name})

    def send_input(self, run: RunState, prompt: str, store: RunStore) -> None:
        store.increment_prompt_count(run.run_id)
        store.append_event(
            run.run_id,
            "permission.requested",
            {
                "permission_id": "perm-remote",
                "prompt": "Approve remote worker action?",
                "options": [{"id": "approve"}, {"id": "deny"}],
            },
        )

    def cancel(self, run: RunState, reason: str | None, store: RunStore) -> None:
        store.append_event(run.run_id, "run.cancelled", {"reason": reason or "cancelled"})

    def resolve_permission(
        self,
        run: RunState,
        permission_id: str,
        payload: dict[str, Any],
        store: RunStore,
    ) -> None:
        super().resolve_permission(run, permission_id, payload, store)
        store.append_event(run.run_id, "run.completed", {"permission_id": permission_id})


def wait_for_status(
    base_url: str,
    run_id: str,
    status: str,
    headers: dict[str, str],
) -> dict[str, object]:
    deadline = time.time() + 5
    current: dict[str, object] = {}
    while time.time() < deadline:
        current = request_json(f"{base_url}/runs/{run_id}", headers=headers)
        if current.get("status") == status:
            return current
        time.sleep(0.03)
    return current


def wait_for_event(
    base_url: str,
    run_id: str,
    event_type: str,
    headers: dict[str, str],
) -> None:
    deadline = time.time() + 5
    while time.time() < deadline:
        events = request_json(f"{base_url}/runs/{run_id}/events.json", headers=headers)
        if event_type in {event["type"] for event in events["events"]}:
            return
        time.sleep(0.03)
    raise AssertionError(f"event not observed: {event_type}")


if __name__ == "__main__":
    unittest.main()
