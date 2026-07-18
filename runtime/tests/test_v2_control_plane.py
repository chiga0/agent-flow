from __future__ import annotations

import os
import unittest
import time
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from unittest import mock

from runtime.cloud_agents_runtime.v2_control_plane import (
    ApprovalConfirmationRequiredError,
    ApprovalConflictError,
    CONVERSATION_PROJECTION_VERSION,
    ConversationConflictError,
    V2ControlPlane,
    cli_result_is_error,
    cli_result_summary,
    extract_feishu_text,
    json_loads,
    nested_text,
    normalize_inbound_channel_payload,
    outbound_channel_payload,
    redact_secret_config,
    v2_event_to_daemon_event,
)


def wait_for_status(control: V2ControlPlane, task_id: str, status: str) -> dict:
    deadline = time.time() + 2
    while time.time() < deadline:
        task = control.get_task(task_id)
        if task["status"] == status:
            return task
        time.sleep(0.02)
    return control.get_task(task_id)


class V2ControlPlaneTest(unittest.TestCase):
    def test_high_risk_approval_is_versioned_confirmed_and_resumes_execution(self):
        control = V2ControlPlane(self.tmp_path())
        conversation = control.create_conversation(
            {
                "goal": "Deploy to production after the release checks",
                "adapter": "fake",
            },
            principal="user_1",
        )
        task_id = conversation["latest_execution"]["task_id"]
        approvals = control.list_approvals(principal="user_1")

        self.assertEqual(control.get_task(task_id)["status"], "waiting_user")
        self.assertEqual(len(approvals), 1)
        self.assertEqual(approvals[0]["impact"]["level"], "high")
        self.assertEqual(
            control.get_conversation(
                conversation["conversation_id"], principal="user_1"
            )["pending_approval_count"],
            1,
        )
        self.assertIn(
            "approval",
            [
                message["kind"]
                for message in control.conversation_messages(
                    conversation["conversation_id"], principal="user_1"
                )
            ],
        )
        snapshot = control.mobile_snapshot(principal="user_1")
        self.assertTrue(snapshot["stateless"])
        self.assertEqual(snapshot["counts"]["pending_approvals"], 1)
        self.assertNotIn("workspace", snapshot)
        notifications = control.mobile_notifications(principal="user_1")
        self.assertEqual(len(notifications), 1)
        self.assertEqual(snapshot["notification_cursor"], notifications[0]["cursor"])
        self.assertEqual(notifications[0]["title"], "高风险操作等待确认")
        self.assertNotIn("Deploy", json.dumps(notifications[0], ensure_ascii=False))
        self.assertNotIn("conversation_id", notifications[0])
        self.assertEqual(control.mobile_notifications(principal="user_2"), [])
        self.assertEqual(
            control.mobile_notifications(
                principal="user_1", after=notifications[0]["cursor"]
            ),
            [],
        )

        approval = approvals[0]
        with self.assertRaises(ApprovalConfirmationRequiredError):
            control.decide_approval(
                approval["approval_id"],
                {"action": "approve", "version": approval["version"]},
                principal="user_1",
            )
        approved = control.decide_approval(
            approval["approval_id"],
            {
                "action": "approve",
                "version": approval["version"],
                "confirmed": True,
            },
            principal="user_1",
            idempotency_key="approve-once",
        )
        repeated = control.decide_approval(
            approval["approval_id"],
            {
                "action": "approve",
                "version": approval["version"],
                "confirmed": True,
            },
            principal="user_1",
            idempotency_key="approve-once",
        )

        self.assertEqual(approved, repeated)
        self.assertEqual(approved["status"], "approved")
        with self.assertRaises(ApprovalConflictError):
            control.decide_approval(
                approval["approval_id"],
                {
                    "action": "reject",
                    "version": approval["version"],
                    "reason": "stale mobile decision",
                },
                principal="user_1",
                idempotency_key="second-device",
            )
        self.assertEqual(wait_for_status(control, task_id, "completed")["status"], "completed")
        self.assertEqual(control.list_approvals(principal="user_1"), [])

    def test_approval_reject_pause_revise_expiry_and_access_boundaries(self):
        control = V2ControlPlane(self.tmp_path())

        def create(action: str, expires_at: str | None = None):
            conversation = control.create_conversation(
                {
                    "goal": f"Prepare controlled operation {action}",
                    "adapter": "fake",
                    "approval": {
                        "intent": f"Run controlled operation {action}",
                        "evidence": [{"type": "command", "summary": "safe fixture"}],
                        "impact": {
                            "level": "low",
                            "summary": "test impact",
                            "affected_resources": ["fixture"],
                            "reversible": True,
                        },
                        "allowed_actions": ["approve", "reject", "pause", "revise"],
                        "scope": {"environment": "test"},
                        "expires_at": expires_at,
                    },
                },
                principal="user_1",
            )
            approval = control.list_approvals(principal="user_1")[0]
            return conversation, approval

        rejected_conversation, rejected = create("reject")
        rejected_result = control.decide_approval(
            rejected["approval_id"],
            {"action": "reject", "version": 1, "reason": "unsafe now"},
            principal="user_1",
        )
        self.assertEqual(rejected_result["status"], "rejected")
        self.assertEqual(
            control.get_task(rejected_conversation["latest_execution"]["task_id"])[
                "status"
            ],
            "cancelled",
        )

        paused_conversation, paused = create("pause")
        control.decide_approval(
            paused["approval_id"],
            {"action": "pause", "version": 1},
            principal="user_1",
        )
        self.assertEqual(
            control.get_task(paused_conversation["latest_execution"]["task_id"])[
                "status"
            ],
            "paused",
        )

        revised_conversation, revised = create("revise")
        control.decide_approval(
            revised["approval_id"],
            {"action": "revise", "version": 1, "reason": "use staging"},
            principal="user_1",
        )
        self.assertEqual(
            control.get_task(revised_conversation["latest_execution"]["task_id"])[
                "status"
            ],
            "waiting_user",
        )
        continued = control.append_conversation_message(
            revised_conversation["conversation_id"],
            "Use staging first and produce a new verification report",
            principal="user_1",
        )
        self.assertTrue(continued["created_execution"])
        self.assertEqual(
            wait_for_status(control, continued["task_id"], "completed")["status"],
            "completed",
        )
        with self.assertRaises(PermissionError):
            control.get_approval(revised["approval_id"], principal="user_2")

        _expired_conversation, expiring = create(
            "expire", expires_at="2099-01-01T00:00:00Z"
        )
        control._db.execute(
            "UPDATE v2_approvals SET expires_at = ? WHERE approval_id = ?",
            ("2000-01-01T00:00:00Z", expiring["approval_id"]),
        )
        control._db.commit()
        self.assertEqual(
            control.get_approval(expiring["approval_id"], principal="user_1")["status"],
            "expired",
        )

        stopped_conversation, stopped = create("stop")
        control.stop_conversation(
            stopped_conversation["conversation_id"],
            principal="user_1",
            reason="cancelled from approval inbox",
        )
        stopped_result = control.get_approval(
            stopped["approval_id"], principal="user_1"
        )
        self.assertEqual(stopped_result["status"], "cancelled")
        self.assertEqual(
            control.get_conversation(
                stopped_conversation["conversation_id"], principal="user_1"
            )["pending_approval_count"],
            0,
        )

    def test_conversation_projection_is_versioned_rebuildable_and_multi_execution(self):
        control = V2ControlPlane(self.tmp_path())
        conversation = control.create_conversation(
            {"goal": "Audit the client conversation model", "adapter": "fake"},
            principal="user_1",
            idempotency_key="conversation-1",
        )
        task_id = conversation["latest_execution"]["task_id"]
        wait_for_status(control, task_id, "completed")

        first_projection = control.conversation_messages(
            conversation["conversation_id"],
            principal="user_1",
        )
        control._db.execute(
            "DELETE FROM v2_conversation_messages WHERE conversation_id = ?",
            (conversation["conversation_id"],),
        )
        control._db.commit()
        rebuilt_projection = control.conversation_messages(
            conversation["conversation_id"],
            principal="user_1",
        )

        self.assertEqual(first_projection, rebuilt_projection)
        self.assertEqual(first_projection[0]["role"], "user")
        self.assertIn("plan", [message["kind"] for message in first_projection])
        self.assertIn("result", [message["kind"] for message in first_projection])
        agent_links = [
            block
            for message in first_projection
            for block in message["content"]
            if block.get("type") == "entity_ref"
            and block.get("entity_type") == "agents"
        ]
        self.assertTrue(agent_links)
        self.assertTrue(all(message["revision"] == 2 for message in first_projection))

        statements: list[str] = []
        control._db.set_trace_callback(statements.append)
        self.assertEqual(
            rebuilt_projection,
            control.conversation_messages(
                conversation["conversation_id"],
                principal="user_1",
            ),
        )
        control._db.set_trace_callback(None)
        self.assertFalse(
            any(
                "DELETE FROM v2_conversation_messages" in statement
                for statement in statements
            ),
            "a current projection must refresh incrementally without full-table churn",
        )

        control._db.execute(
            "UPDATE v2_conversations SET projection_version = 0 WHERE conversation_id = ?",
            (conversation["conversation_id"],),
        )
        control._db.commit()
        version_upgrade_statements: list[str] = []
        control._db.set_trace_callback(version_upgrade_statements.append)
        upgraded_projection = control.conversation_messages(
            conversation["conversation_id"],
            principal="user_1",
        )
        control._db.set_trace_callback(None)
        self.assertEqual(rebuilt_projection, upgraded_projection)
        self.assertTrue(
            any(
                "DELETE FROM v2_conversation_messages" in statement
                for statement in version_upgrade_statements
            ),
            "a projection rule upgrade must trigger one deterministic rebuild",
        )
        self.assertEqual(
            control.get_conversation(
                conversation["conversation_id"], principal="user_1"
            )["projection_version"],
            CONVERSATION_PROJECTION_VERSION,
        )

        continued = control.append_conversation_message(
            conversation["conversation_id"],
            "Now generate the implementation checklist",
            principal="user_1",
            idempotency_key="message-1",
        )
        repeated = control.append_conversation_message(
            conversation["conversation_id"],
            "This duplicate must not create another execution",
            principal="user_1",
            idempotency_key="message-1",
        )
        current = control.get_conversation(
            conversation["conversation_id"],
            principal="user_1",
        )

        self.assertTrue(continued["created_execution"])
        self.assertEqual(repeated, continued)
        self.assertEqual(len(current["executions"]), 2)
        self.assertEqual(current["latest_execution"]["sequence"], 2)

    def test_conversation_projection_pages_latest_messages_without_duplicates(self):
        control = V2ControlPlane(self.tmp_path())
        task = control.create_task(
            {
                "goal": "Build a long conversation projection",
                "adapter": "fake",
                "_defer_runner": True,
            },
            principal="user_1",
        )
        conversation = control.conversation_for_task(
            task["task_id"], principal="user_1"
        )
        with control._lock:
            for index in range(205):
                control._append_event_locked(
                    task["task_id"],
                    "user.message",
                    "user_1",
                    {"message": f"message {index}"},
                )
            control._db.commit()

        latest = control.conversation_messages(
            conversation["conversation_id"], principal="user_1"
        )
        older = control.conversation_messages(
            conversation["conversation_id"],
            before=latest[0]["cursor"],
            limit=200,
            principal="user_1",
        )

        self.assertEqual(len(latest), 200)
        self.assertEqual(len(older), 7)
        self.assertLess(older[-1]["cursor"], latest[0]["cursor"])
        self.assertEqual(
            len({message["message_id"] for message in [*older, *latest]}),
            207,
        )

    def test_conversation_access_versioning_and_legacy_task_projection(self):
        control = V2ControlPlane(self.tmp_path())
        task = control.create_task(
            {"goal": "Keep old task links working", "adapter": "fake"},
            principal="user_1",
        )
        projected = control.conversation_for_task(task["task_id"], principal="user_1")
        updated = control.update_conversation(
            projected["conversation_id"],
            {
                "title": "Pinned legacy conversation",
                "pinned": True,
                "version": projected["version"],
            },
            principal="user_1",
        )

        self.assertEqual(updated["title"], "Pinned legacy conversation")
        self.assertIsNotNone(updated["pinned_at"])
        with self.assertRaises(ConversationConflictError):
            control.update_conversation(
                projected["conversation_id"],
                {"archived": True, "version": projected["version"]},
                principal="user_1",
            )
        with self.assertRaises(PermissionError):
            control.get_conversation(
                projected["conversation_id"],
                principal="user_2",
            )

    def test_create_task_builds_plan_events_and_result(self):
        with self.subTest("single-agent fast path"):
            control = V2ControlPlane(self.tmp_path())

            task = control.create_task(
                {
                    "goal": "Draft a release checklist for the V2 product",
                    "adapter": "fake",
                },
                principal="user_1",
                idempotency_key="task-key-1",
            )

            self.assertTrue(task["task_id"].startswith("task_"))
            self.assertEqual(task["plan"]["strategy"], "single-agent-fast-path")
            self.assertEqual(task["progress"]["total_steps"], 1)

            completed = wait_for_status(control, task["task_id"], "completed")

            self.assertEqual(completed["status"], "completed")
            self.assertEqual(completed["result"]["evaluation"]["status"], "passed")
            self.assertEqual(completed["progress"]["percent"], 100)
            self.assertEqual(
                [event["type"] for event in control.events(task["task_id"])][:2],
                ["task.created", "plan.created"],
            )

    def test_complex_task_uses_orchestrator_workers_plan(self):
        control = V2ControlPlane(self.tmp_path())
        goal = "Build a complete tenant-aware agent platform. " * 5

        task = control.create_task({"goal": goal, "mode": "auto"}, principal="user_1")

        self.assertEqual(task["plan"]["strategy"], "orchestrator-workers")
        self.assertEqual(
            [agent["role"] for agent in task["plan"]["agent_tasks"]],
            ["brain", "builder", "reviewer"],
        )

    def test_explicit_single_mode_does_not_expand_a_long_goal(self):
        control = V2ControlPlane(self.tmp_path())
        goal = "Audit this repository and report evidence without changing files. " * 5

        task = control.create_task(
            {"goal": goal, "mode": "single", "adapter": "fake"},
            principal="user_1",
        )

        self.assertEqual(task["plan"]["strategy"], "single-agent-fast-path")
        self.assertEqual(task["progress"]["total_steps"], 1)
        self.assertEqual(
            [agent["role"] for agent in task["plan"]["agent_tasks"]],
            ["agent"],
        )
        wait_for_status(control, task["task_id"], "completed")
        control.close()

    def test_cancel_task_stops_open_work_and_is_idempotent(self):
        control = V2ControlPlane(self.tmp_path())
        task = control.create_task(
            {"goal": "Run a long multi agent task " * 20, "mode": "multi-agent"},
            principal="user_1",
        )

        cancelled = control.cancel_task(
            task["task_id"],
            principal="user_1",
            reason="user stopped the conversation",
        )
        cancelled_again = control.cancel_task(
            task["task_id"],
            principal="user_1",
        )

        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(cancelled_again["status"], "cancelled")
        self.assertEqual(control.workflow(task["task_id"])["run"]["status"], "cancelled")
        self.assertIn(
            "task.cancelled",
            [event["type"] for event in control.events(task["task_id"])],
        )

    def test_cancel_task_terminates_a_live_cli_adapter(self):
        control = V2ControlPlane(self.tmp_path())
        script = control.root / "slow-codex-adapter"
        child_ready = control.root / "child-ready"
        child_terminated = control.root / "child-terminated"
        child_code = (
            "import pathlib, signal, sys, time; "
            f"ready=pathlib.Path({str(child_ready)!r}); "
            f"terminated=pathlib.Path({str(child_terminated)!r}); "
            "signal.signal(signal.SIGTERM, lambda *_: "
            "(terminated.write_text('yes'), sys.exit(0))); "
            "ready.write_text('yes'); time.sleep(30)"
        )
        script.write_text(
            "#!/usr/bin/env python3\n"
            "import subprocess, sys, time\n"
            f"subprocess.Popen([sys.executable, '-c', {child_code!r}])\n"
            "time.sleep(30)\n",
            encoding="utf-8",
        )
        script.chmod(0o755)
        old_enabled = os.environ.get("V2_ENABLE_REAL_CLI_ADAPTERS")
        old_command = os.environ.get("V2_CODEX_CLI_COMMAND")
        try:
            os.environ["V2_ENABLE_REAL_CLI_ADAPTERS"] = "1"
            os.environ["V2_CODEX_CLI_COMMAND"] = str(script)
            task = control.create_task(
                {"goal": "Run a cancellable CLI task", "adapter": "codex"},
                principal="user_1",
            )
            deadline = time.time() + 2
            process = None
            while time.time() < deadline:
                process = control._processes.get(task["task_id"])
                if process is not None:
                    break
                time.sleep(0.01)
            ready_deadline = time.time() + 2
            while time.time() < ready_deadline and not child_ready.exists():
                time.sleep(0.01)

            self.assertIsNotNone(process)
            self.assertTrue(child_ready.exists())
            control.cancel_task(task["task_id"], principal="user_1")
            process.wait(timeout=2)
            terminated_deadline = time.time() + 2
            while time.time() < terminated_deadline and not child_terminated.exists():
                time.sleep(0.01)

            self.assertIsNotNone(process.returncode)
            self.assertTrue(child_terminated.exists())
            self.assertEqual(control.get_task(task["task_id"])["status"], "cancelled")
        finally:
            restore_env("V2_ENABLE_REAL_CLI_ADAPTERS", old_enabled)
            restore_env("V2_CODEX_CLI_COMMAND", old_command)
            control.close()

    def test_dispatch_selects_requested_adapter_unit_and_channel(self):
        control = V2ControlPlane(self.tmp_path())

        task = control.create_task(
            {
                "goal": "Implement a Codex-backed code review",
                "adapter": "codex",
                "channel": "feishu",
                "mode": "workflow",
            },
            principal="user_1",
        )
        dispatch = task["metadata"]["dispatch"]

        self.assertEqual(task["adapter"], "codex")
        self.assertEqual(dispatch["adapter_protocol"], "ACP/A2A")
        self.assertEqual(dispatch["execution_unit_id"], "local-dev")
        self.assertEqual(dispatch["channel"], "feishu")
        self.assertTrue(dispatch["delivery"]["requires_connector"])
        self.assertIn("codex", [item["adapter"] for item in control.adapter_catalog()])
        self.assertIn(
            "dispatch.selected",
            [event["type"] for event in control.events(task["task_id"])],
        )

        old_auto = os.environ.get("V2_AUTO_ADAPTER")
        old_enabled = os.environ.get("V2_ENABLE_REAL_CLI_ADAPTERS")
        old_command = os.environ.get("V2_QWEN_CODE_COMMAND")
        try:
            os.environ["V2_AUTO_ADAPTER"] = "qwen"
            os.environ["V2_ENABLE_REAL_CLI_ADAPTERS"] = "1"
            os.environ["V2_QWEN_CODE_COMMAND"] = "/usr/bin/true"
            self.assertEqual(
                control._dispatch_decision(
                    requested_adapter="auto",
                    channel="web",
                    strategy="single-agent-fast-path",
                )["adapter"],
                "qwen",
            )
            os.environ["V2_QWEN_CODE_COMMAND"] = "/missing/qwen"
            self.assertEqual(
                control._dispatch_decision(
                    requested_adapter="auto",
                    channel="web",
                    strategy="single-agent-fast-path",
                )["adapter"],
                "fake",
            )
        finally:
            restore_env("V2_AUTO_ADAPTER", old_auto)
            restore_env("V2_ENABLE_REAL_CLI_ADAPTERS", old_enabled)
            restore_env("V2_QWEN_CODE_COMMAND", old_command)

    def test_remote_execution_unit_is_selected_and_uses_bound_worker_bridge(self):
        calls = []
        control = V2ControlPlane(self.tmp_path(), auto_start=False)
        control.register_execution_unit(
            {
                "unit_id": "ecs-hk",
                "kind": "ecs",
                "labels": {"region": "hk"},
                "adapters": ["qwen"],
                "features": ["remote-worker", "artifacts"],
            }
        )

        def execute_remote(task_id, agent, prompt, unit):
            calls.append((task_id, agent["agent_task_id"], prompt, unit["unit_id"]))
            return {
                "adapter": "qwen",
                "protocol": "ACP/A2A",
                "execution_mode": "remote-worker",
                "exit_code": 0,
                "success": True,
                "message": "远端 Qwen 已完成",
                "summary": "远端 Qwen 已完成",
                "raw_output": "远端 Qwen 已完成",
                "stderr": "",
                "workspace": "/srv/agentflow/workspace",
                "remote_run_id": "run_remote_1",
                "worker_id": "worker-hk",
                "execution_unit_id": unit["unit_id"],
            }

        control.bind_remote_agent_executor(execute_remote)
        control.start()
        task = control.create_task(
            {
                "goal": "Run a remote code audit",
                "adapter": "qwen",
                "mode": "single",
                "metadata": {"execution_unit_id": "ecs-hk"},
            },
            principal="user_1",
        )
        completed = wait_for_status(control, task["task_id"], "completed")

        self.assertEqual(completed["metadata"]["dispatch"]["execution_unit_id"], "ecs-hk")
        self.assertEqual(len(calls), 1)
        self.assertIn("Do not create subagents", calls[0][2])
        self.assertEqual(
            control.artifacts(task["task_id"])[0]["content"]["adapter"][
                "execution_mode"
            ],
            "remote-worker",
        )
        with self.assertRaises(RuntimeError):
            control._dispatch_decision(
                requested_adapter="qwen",
                channel="web",
                strategy="single-agent-fast-path",
                requested_unit_id="missing",
            )
        control.close()

    def test_durable_workflow_artifact_evaluation_retry_and_replay(self):
        control = V2ControlPlane(self.tmp_path())
        task = control.create_task(
            {
                "goal": "Build and review a durable workflow",
                "adapter": "codex",
                "mode": "workflow",
            },
            principal="user_1",
        )

        completed = wait_for_status(control, task["task_id"], "completed")
        workflow = control.workflow(task["task_id"])
        artifacts = control.artifacts(task["task_id"])
        evaluations = control.evaluations(task["task_id"])

        self.assertEqual(completed["status"], "completed")
        self.assertEqual(workflow["run"]["status"], "completed")
        self.assertEqual(workflow["run"]["engine"], "local-sqlite-dag")
        self.assertEqual(len(workflow["steps"]), 3)
        self.assertTrue(all(step["status"] == "completed" for step in workflow["steps"]))
        self.assertEqual(len(artifacts), 3)
        self.assertEqual(len(evaluations), 3)
        self.assertEqual(
            artifacts[0]["content"]["adapter"]["protocol"],
            "ACP/A2A",
        )

        replay = control.replay_task(task["task_id"], principal="user_1")

        self.assertEqual(replay["status"], "created")
        self.assertEqual(replay["snapshot"]["task"]["task_id"], task["task_id"])
        self.assertIn(
            "task.replay_created",
            [event["type"] for event in control.events(task["task_id"])],
        )

        retried = control.retry_task(task["task_id"], principal="user_1")
        self.assertIn(retried["status"], {"queued", "running", "completed"})
        retried_completed = wait_for_status(control, task["task_id"], "completed")

        self.assertEqual(retried_completed["status"], "completed")
        self.assertGreaterEqual(control.workflow(task["task_id"])["run"]["attempt"], 2)

    def test_control_plane_boundary_paths_and_real_cli_adapter(self):
        control = V2ControlPlane(self.tmp_path())

        with self.assertRaises(ValueError):
            control.register_execution_unit({"unit_id": " "})
        with self.assertRaises(KeyError):
            control.workflow("missing")
        with self.assertRaises(KeyError):
            control.artifacts("missing")
        with self.assertRaises(KeyError):
            control.evaluations("missing")
        with self.assertRaises(KeyError):
            control.replays("missing")
        with self.assertRaises(KeyError):
            control.retry_task("missing", principal="user_1")

        task = control.create_task({"goal": "Hold retry while running"}, principal="user_1")
        task = wait_for_status(control, task["task_id"], "completed")
        control._db.execute(
            "UPDATE v2_tasks SET status = ? WHERE task_id = ?",
            ("running", task["task_id"]),
        )
        control._db.commit()
        with self.assertRaises(ValueError):
            control.retry_task(task["task_id"], principal="user_1")

        control._db.execute("DELETE FROM v2_execution_units")
        control._db.commit()
        control.register_execution_unit({"unit_id": "fake-only", "adapters": ["fake"]})
        self.assertEqual(control._select_execution_unit("codex")["unit_id"], "fake-only")
        control._db.execute("DELETE FROM v2_execution_units")
        control._db.commit()
        with self.assertRaises(RuntimeError):
            control._select_execution_unit("codex")
        control._db.execute("DELETE FROM v2_channels")
        control._db.commit()
        with self.assertRaises(RuntimeError):
            control._channel_by_platform("feishu")

        script = control.root / "codex-adapter"
        script.write_text("#!/bin/sh\ncat\n", encoding="utf-8")
        script.chmod(0o755)
        agent = {
            "agent_task_id": "at_test",
            "role": "builder",
            "adapter": "codex",
            "goal": "Use a real CLI bridge",
            "depends_on": [],
            "artifact_contract": {"artifacts": ["final_summary"]},
        }
        old_enabled = os.environ.get("V2_ENABLE_REAL_CLI_ADAPTERS")
        old_command = os.environ.get("V2_CODEX_CLI_COMMAND")
        try:
            os.environ["V2_ENABLE_REAL_CLI_ADAPTERS"] = "1"
            os.environ["V2_CODEX_CLI_COMMAND"] = str(script)
            result = control._execute_agent_adapter(task["task_id"], agent)
            self.assertEqual(result["execution_mode"], "real-cli")
            self.assertIn("agentflow-v2-acp-a2a", result["summary"])
            with mock.patch(
                "runtime.cloud_agents_runtime.v2_control_plane.subprocess.Popen",
                side_effect=OSError("boom"),
            ):
                failed = control._execute_agent_adapter(task["task_id"], agent)
            self.assertEqual(failed["execution_mode"], "cli-error")
        finally:
            restore_env("V2_ENABLE_REAL_CLI_ADAPTERS", old_enabled)
            restore_env("V2_CODEX_CLI_COMMAND", old_command)

    def test_qwen_cli_uses_noninteractive_protocol_and_extracts_result(self):
        control = V2ControlPlane(self.tmp_path())
        task = control.create_task(
            {"goal": "Inspect the current workspace safely"}, principal="user_1"
        )
        task = wait_for_status(control, task["task_id"], "completed")
        workspace = control.root / "workspace"
        workspace.mkdir()
        capture = control.root / "qwen-invocation.json"
        script = control.root / "qwen-adapter"
        script.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, pathlib, sys\n"
            "payload = {'args': sys.argv[1:], 'cwd': os.getcwd(), "
            "'real_cli': os.environ.get('V2_ENABLE_REAL_CLI_ADAPTERS'), "
            "'auto_adapter': os.environ.get('V2_AUTO_ADAPTER')}\n"
            f"pathlib.Path({str(capture)!r}).write_text(json.dumps(payload))\n"
            "print(json.dumps([{'type': 'result', 'is_error': False, "
            "'result': '真实 Qwen 验证完成'}]))\n",
            encoding="utf-8",
        )
        script.chmod(0o755)
        agent = {
            "agent_task_id": "at_qwen",
            "role": "builder",
            "title": "Qwen builder",
            "adapter": "qwen",
            "goal": "Use the qwen protocol",
            "depends_on": [],
            "artifact_contract": {"artifacts": ["final_summary"]},
        }
        old_enabled = os.environ.get("V2_ENABLE_REAL_CLI_ADAPTERS")
        old_command = os.environ.get("V2_QWEN_CODE_COMMAND")
        old_workspace = os.environ.get("V2_WORKSPACE_ROOT")
        try:
            os.environ["V2_ENABLE_REAL_CLI_ADAPTERS"] = "1"
            os.environ["V2_QWEN_CODE_COMMAND"] = str(script)
            os.environ["V2_WORKSPACE_ROOT"] = str(workspace)
            result = control._execute_agent_adapter(task["task_id"], agent)
            invocation = json.loads(capture.read_text(encoding="utf-8"))

            self.assertEqual(result["execution_mode"], "real-cli")
            self.assertTrue(result["success"])
            self.assertEqual(result["summary"], "真实 Qwen 验证完成")
            self.assertEqual(
                os.path.realpath(invocation["cwd"]), os.path.realpath(workspace)
            )
            self.assertIn("--prompt", invocation["args"])
            prompt = invocation["args"][invocation["args"].index("--prompt") + 1]
            self.assertIn("Do not create subagents", prompt)
            self.assertIn("--output-format", invocation["args"])
            self.assertEqual(
                invocation["args"][invocation["args"].index("--output-format") + 1],
                "stream-json",
            )
            self.assertEqual(invocation["real_cli"], "0")
            self.assertEqual(invocation["auto_adapter"], "fake")
            self.assertNotIn("agentflow-v2-acp-a2a", invocation["args"])
        finally:
            restore_env("V2_ENABLE_REAL_CLI_ADAPTERS", old_enabled)
            restore_env("V2_QWEN_CODE_COMMAND", old_command)
            restore_env("V2_WORKSPACE_ROOT", old_workspace)

    def test_qwen_result_parser_ignores_startup_noise_and_supports_ndjson(self):
        noisy = (
            "Warning: optional MCP server failed to start.\n"
            '[{"type":"system","subtype":"init"},'
            '{"type":"result","is_error":false,"result":"审计结论已验证"}]'
        )
        ndjson_error = (
            '{"type":"system","subtype":"init"}\n'
            '{"type":"result","is_error":true,"result":"认证失败"}\n'
        )
        adjacent_documents = (
            '{"type":"system","subtype":"init"}'
            "loading headless response..."
            '[{"type":"result","is_error":false,"result":"最终报告"}]'
        )

        self.assertEqual(cli_result_summary("qwen", noisy), "审计结论已验证")
        self.assertFalse(cli_result_is_error(noisy))
        self.assertEqual(cli_result_summary("qwen", ndjson_error), "认证失败")
        self.assertTrue(cli_result_is_error(ndjson_error))
        self.assertEqual(cli_result_summary("qwen", adjacent_documents), "最终报告")

    def test_qwen_json_error_and_process_failure_fail_the_task(self):
        control = V2ControlPlane(self.tmp_path())
        script = control.root / "qwen-error-adapter"
        script.write_text(
            "#!/usr/bin/env python3\n"
            "import json\n"
            "print(json.dumps([{'type': 'result', 'is_error': True, "
            "'result': 'authentication failed'}]))\n",
            encoding="utf-8",
        )
        script.chmod(0o755)
        old_enabled = os.environ.get("V2_ENABLE_REAL_CLI_ADAPTERS")
        old_command = os.environ.get("V2_QWEN_CODE_COMMAND")
        old_workspace = os.environ.get("V2_WORKSPACE_ROOT")
        try:
            os.environ["V2_ENABLE_REAL_CLI_ADAPTERS"] = "1"
            os.environ["V2_QWEN_CODE_COMMAND"] = str(script)
            os.environ["V2_WORKSPACE_ROOT"] = str(control.root)
            task = control.create_task(
                {"goal": "This qwen run must fail", "adapter": "qwen"},
                principal="user_1",
            )
            failed = wait_for_status(control, task["task_id"], "failed")

            self.assertEqual(failed["status"], "failed")
            workflow = control.workflow(task["task_id"])
            self.assertEqual(workflow["run"]["status"], "failed")
            self.assertEqual(workflow["steps"][0]["status"], "failed")
            self.assertIn("authentication failed", failed["result"]["error"])
        finally:
            restore_env("V2_ENABLE_REAL_CLI_ADAPTERS", old_enabled)
            restore_env("V2_QWEN_CODE_COMMAND", old_command)
            restore_env("V2_WORKSPACE_ROOT", old_workspace)

    def test_partial_failure_can_be_accepted_or_resume_only_unfinished_agents(self):
        control = V2ControlPlane(self.tmp_path())
        allow_success = control.root / "allow-builder-success"
        invocation_log = control.root / "qwen-role-log"
        script = control.root / "qwen-partial-adapter"
        script.write_text(
            "#!/usr/bin/env python3\n"
            "import json, pathlib, sys\n"
            f"sentinel = pathlib.Path({str(allow_success)!r})\n"
            f"log = pathlib.Path({str(invocation_log)!r})\n"
            "prompt = sys.argv[sys.argv.index('--prompt') + 1]\n"
            "role = next((name for name in ('brain', 'builder', 'reviewer')\n"
            "    if f'Your role: {name}' in prompt), 'agent')\n"
            "with log.open('a', encoding='utf-8') as stream: stream.write(role + '\\n')\n"
            "failed = role == 'builder' and not sentinel.exists()\n"
            "result = 'builder failed safely' if failed else role + ' verified'\n"
            "print(json.dumps([{'type': 'result', 'is_error': failed, "
            "'result': result}]))\n",
            encoding="utf-8",
        )
        script.chmod(0o755)
        old_enabled = os.environ.get("V2_ENABLE_REAL_CLI_ADAPTERS")
        old_command = os.environ.get("V2_QWEN_CODE_COMMAND")
        old_workspace = os.environ.get("V2_WORKSPACE_ROOT")
        try:
            os.environ["V2_ENABLE_REAL_CLI_ADAPTERS"] = "1"
            os.environ["V2_QWEN_CODE_COMMAND"] = str(script)
            os.environ["V2_WORKSPACE_ROOT"] = str(control.root)

            partial_task = control.create_task(
                {
                    "goal": "Research, build, and review a recoverable result",
                    "adapter": "qwen",
                    "mode": "multi-agent",
                },
                principal="user_1",
            )
            self.assertEqual(
                wait_for_status(control, partial_task["task_id"], "failed")["status"],
                "failed",
            )
            with self.assertRaises(PermissionError):
                control.accept_partial_result(
                    partial_task["task_id"], principal="user_2"
                )
            accepted = control.accept_partial_result(
                partial_task["task_id"], principal="user_1"
            )
            self.assertEqual(accepted["status"], "completed")
            self.assertTrue(accepted["result"]["partial"])
            self.assertEqual(accepted["result"]["evaluation"]["status"], "partial")

            retry_task = control.create_task(
                {
                    "goal": "Retry only the unfinished recovery stages",
                    "adapter": "qwen",
                    "mode": "multi-agent",
                },
                principal="user_1",
            )
            self.assertEqual(
                wait_for_status(control, retry_task["task_id"], "failed")["status"],
                "failed",
            )
            allow_success.write_text("ok", encoding="utf-8")
            control.retry_failed_steps(retry_task["task_id"], principal="user_1")
            completed = wait_for_status(control, retry_task["task_id"], "completed")
            self.assertEqual(completed["status"], "completed")
            started_roles = [
                event["actor"]
                for event in control.events(retry_task["task_id"])
                if event["type"] == "agent_task.started"
            ]
            self.assertEqual(started_roles.count("brain"), 1)
            self.assertEqual(started_roles.count("builder"), 2)
            self.assertEqual(started_roles.count("reviewer"), 1)
        finally:
            restore_env("V2_ENABLE_REAL_CLI_ADAPTERS", old_enabled)
            restore_env("V2_QWEN_CODE_COMMAND", old_command)
            restore_env("V2_WORKSPACE_ROOT", old_workspace)

    def test_idempotency_key_returns_existing_task(self):
        control = V2ControlPlane(self.tmp_path())

        first = control.create_task(
            {"goal": "Summarize the architecture"},
            principal="user_1",
            idempotency_key="same-key",
        )
        second = control.create_task(
            {"goal": "This should not create another task"},
            principal="user_1",
            idempotency_key="same-key",
        )

        self.assertEqual(second["task_id"], first["task_id"])
        self.assertEqual(len(control.list_tasks()), 1)

    def test_admin_overview_and_execution_unit_registration(self):
        control = V2ControlPlane(self.tmp_path())

        unit = control.register_execution_unit(
            {
                "unit_id": "docker-a",
                "kind": "docker",
                "labels": {"region": "local"},
                "adapters": ["fake", "qwen"],
                "features": ["artifacts", "events"],
            }
        )
        overview = control.admin_overview()

        self.assertEqual(unit["unit_id"], "docker-a")
        self.assertTrue(
            any(item["platform"] == "feishu" for item in overview["channels"])
        )
        self.assertEqual(overview["reliability"]["idempotency"], "enabled")

    def test_channel_config_inbound_outbound_and_redaction(self):
        with capture_http_posts() as sink:
            control = V2ControlPlane(self.tmp_path())
            channel = control.configure_channel(
                "feishu",
                {
                    "webhook_url": sink["url"],
                    "callback_token": "callback-secret",
                    "app_secret": "app-secret",
                },
            )

            self.assertEqual(channel["status"], "configured")
            self.assertEqual(channel["config"]["webhook_url"], "<configured>")
            self.assertEqual(channel["config"]["callback_token"], "<configured>")

            with self.assertRaises(PermissionError):
                control.receive_channel_message(
                    "feishu",
                    {
                        "event": {
                            "message": {
                                "message_id": "msg_bad",
                                "content": '{"text":"bad"}',
                            }
                        }
                    },
                    headers={"x-agentflow-channel-token": "wrong"},
                )

            inbound = control.receive_channel_message(
                "feishu",
                {
                    "event": {
                        "sender": {"sender_id": {"open_id": "ou_1"}},
                        "message": {
                            "message_id": "msg_1",
                            "content": '{"text":"Create a weekly ops report"}',
                        },
                    }
                },
                headers={"x-agentflow-channel-token": "callback-secret"},
            )
            outbound = control.send_channel_message(
                "feishu",
                {
                    "task_id": inbound["task"]["task_id"],
                    "message": "Accepted by AgentFlow",
                },
            )
            messages = control.channel_messages("feishu")

            self.assertTrue(inbound["accepted"])
            self.assertEqual(inbound["message"]["direction"], "inbound")
            self.assertEqual(outbound["status"], "sent")
            self.assertEqual(len(sink["posts"]), 1)
            self.assertEqual(
                sink["posts"][0]["body"]["content"]["text"],
                "Accepted by AgentFlow",
            )
            self.assertEqual(
                {message["direction"] for message in messages},
                {"inbound", "outbound"},
            )

    def test_channel_error_paths_and_payload_normalizers(self):
        control = V2ControlPlane(self.tmp_path())

        with self.assertRaises(ValueError):
            control.configure_channel("email", {})
        with self.assertRaises(ValueError):
            control.receive_channel_message("email", {"text": "nope"})
        with self.assertRaises(ValueError):
            control.receive_channel_message("wecom", {"Content": ""})
        with self.assertRaises(ValueError):
            control.send_channel_message("email", {"message": "nope"})
        with self.assertRaises(ValueError):
            control.send_channel_message("web", {"message": " "})

        queued = control.send_channel_message("dingtalk", {"text": "hello"})
        self.assertEqual(queued["status"], "queued")
        failed = control.configure_channel(
            "wecom",
            {"webhook_url": "http://127.0.0.1:1/unreachable"},
        )
        self.assertEqual(failed["status"], "configured")
        failed_message = control.send_channel_message("wecom", {"message": "hello"})
        self.assertEqual(failed_message["status"], "failed")

        dingtalk = normalize_inbound_channel_payload(
            "dingtalk",
            {
                "text": {"content": "ding"},
                "senderStaffId": "staff",
                "conversationId": "conv",
                "msgId": "msg_ding",
            },
        )
        wecom = normalize_inbound_channel_payload(
            "wecom",
            {"Content": "wx", "FromUserName": "user", "MsgId": "msg_wx"},
        )
        generic = normalize_inbound_channel_payload(
            "web",
            {"message": "web", "sender": {"id": "u"}, "message_id": "m_web"},
        )

        self.assertEqual(dingtalk["text"], "ding")
        self.assertEqual(wecom["sender"]["from_user"], "user")
        self.assertEqual(generic["idempotency_key"], "m_web")
        self.assertIsNone(nested_text({"text": "plain"}, ["text", "content"]))
        self.assertEqual(extract_feishu_text({"content": "not-json"}), "not-json")
        self.assertEqual(extract_feishu_text({"content": {"text": "dict"}}), "dict")
        self.assertIsNone(extract_feishu_text({"content": {"other": "x"}}))
        self.assertEqual(outbound_channel_payload("dingtalk", "x")["msgtype"], "text")
        self.assertEqual(
            redact_secret_config([{"token": "secret"}, {"safe": "ok"}])[0]["token"],
            "<configured>",
        )

    def test_webshell_event_projection(self):
        control = V2ControlPlane(self.tmp_path())
        task = control.create_task({"goal": "Render webshell"}, principal="user_1")
        completed = wait_for_status(control, task["task_id"], "completed")
        control.append_message(completed["task_id"], "follow up", principal="user_1")

        events = control.webshell_events(completed["task_id"])
        self.assertTrue(events)
        self.assertEqual(events[0]["type"], "session_update")
        self.assertEqual(events[0]["_meta"]["source"], "agentflow-v2-webshell")
        with self.assertRaises(KeyError):
            control.webshell_events("missing")

        projected = v2_event_to_daemon_event(
            {
                "task_id": "task",
                "sequence": 9,
                "type": "task.completed",
                "payload": {"summary": "done"},
                "created_at": "2026-07-15T00:00:00Z",
            }
        )
        self.assertIn("done", projected["data"]["update"]["content"]["text"])

    def test_admin_tenant_rbac_ha_and_unit_discovery(self):
        control = V2ControlPlane(self.tmp_path())
        old_units = os.environ.get("V2_EXECUTION_UNITS_JSON")
        old_database = os.environ.get("V2_DATABASE_URL")
        old_queue = os.environ.get("V2_QUEUE_URL")
        old_temporal = os.environ.get("TEMPORAL_ADDRESS")
        try:
            os.environ["V2_EXECUTION_UNITS_JSON"] = (
                '[{"unit_id":"ecs-prod-a","kind":"ecs","adapters":["qwen","codex"],'
                '"labels":{"region":"cn-hangzhou"}},{"unit_id":"nas-local","kind":"nas",'
                '"adapters":["fake"],"resources":{"memory_mb":4096}}]'
            )
            os.environ["V2_DATABASE_URL"] = "postgresql://user:pass@db/agentflow"
            os.environ["V2_QUEUE_URL"] = "redis://redis:6379/0"
            os.environ["TEMPORAL_ADDRESS"] = "temporal:7233"

            tenant = control.upsert_tenant(
                {
                    "tenant_id": "tenant_acme",
                    "name": "Acme",
                    "settings": {"channels": ["web", "feishu"]},
                },
                principal="owner@example.com",
            )
            user = control.upsert_tenant_user(
                "tenant_acme",
                {"email": "ops@example.com", "roles": ["operator"]},
            )
            policy = control.upsert_rbac_policy(
                "tenant_acme",
                {"role": "operator", "permissions": ["tasks:*", "channels:*"]},
            )
            discovery = control.discover_execution_units()
            ha = control.ha_config()
            workflow = control.workflow_engine_status()

            self.assertEqual(tenant["name"], "Acme")
            self.assertEqual(user["roles"], ["operator"])
            self.assertEqual(policy["permissions"], ["tasks:*", "channels:*"])
            self.assertEqual(len(discovery["discovered"]), 2)
            self.assertTrue(ha["database"]["configured"])
            self.assertTrue(ha["queue"]["configured"])
            self.assertEqual(workflow["active_engine"], "temporal")
        finally:
            restore_env("V2_EXECUTION_UNITS_JSON", old_units)
            restore_env("V2_DATABASE_URL", old_database)
            restore_env("V2_QUEUE_URL", old_queue)
            restore_env("TEMPORAL_ADDRESS", old_temporal)

        with self.assertRaises(ValueError):
            control.upsert_tenant({"tenant_id": " ", "name": " "}, principal="owner")
        with self.assertRaises(ValueError):
            control.upsert_tenant_user("tenant_acme", {})
        with self.assertRaises(ValueError):
            control.upsert_tenant_user("tenant_acme", {"email": "bad", "roles": "member"})
        with self.assertRaises(ValueError):
            control.upsert_rbac_policy("tenant_acme", {"permissions": ["tasks:read"]})
        with self.assertRaises(ValueError):
            control.upsert_rbac_policy(
                "tenant_acme",
                {"role": "member", "permissions": "tasks:read"},
            )

        old_units = os.environ.get("V2_EXECUTION_UNITS_JSON")
        try:
            os.environ["V2_EXECUTION_UNITS_JSON"] = "{}"
            with self.assertRaises(ValueError):
                control.discover_execution_units()
            os.environ["V2_EXECUTION_UNITS_JSON"] = "[1]"
            with self.assertRaises(ValueError):
                control.discover_execution_units()
        finally:
            restore_env("V2_EXECUTION_UNITS_JSON", old_units)


    def test_append_message_writes_canonical_event(self):
        control = V2ControlPlane(self.tmp_path())
        task = control.create_task({"goal": "Review logs"}, principal="user_1")

        event = control.append_message(
            task["task_id"],
            "Please include risk summary",
            principal="user_1",
        )

        self.assertEqual(event["type"], "user.message")
        self.assertEqual(event["payload"]["message"], "Please include risk summary")

    def test_capabilities_and_validation_errors(self):
        control = V2ControlPlane(self.tmp_path())

        self.assertIn("task_first_api", control.capabilities()["features"])
        self.assertEqual(json_loads(None), {})
        with self.assertRaises(ValueError):
            control.create_task({"goal": " "}, principal="user_1")
        with self.assertRaises(KeyError):
            control.get_task("missing")
        with self.assertRaises(KeyError):
            control.events("missing")
        with self.assertRaises(ValueError):
            control.append_message("missing", " ", principal="user_1")
        with self.assertRaises(KeyError):
            control.append_message("missing", "hello", principal="user_1")

    def test_runner_recovery_and_terminal_guard(self):
        root = self.tmp_path()
        control = V2ControlPlane(root)
        task = control.create_task({"goal": "Recover this queued task"}, principal="user_1")
        completed = wait_for_status(control, task["task_id"], "completed")

        control._ensure_runner(completed["task_id"])
        control._ensure_runner("missing")
        control._run_task("missing")
        control._db.execute(
            "UPDATE v2_tasks SET status = ? WHERE task_id = ?",
            ("queued", completed["task_id"]),
        )
        control._db.commit()

        recovered = V2ControlPlane(root)
        recovered_task = wait_for_status(recovered, completed["task_id"], "completed")
        self.assertEqual(recovered_task["status"], "completed")

    def test_runner_failure_and_active_thread_guard(self):
        control = V2ControlPlane(self.tmp_path())
        task = control.create_task({"goal": "Exercise failure path"}, principal="user_1")
        completed = wait_for_status(control, task["task_id"], "completed")
        control._db.execute(
            "UPDATE v2_tasks SET status = ? WHERE task_id = ?",
            ("queued", completed["task_id"]),
        )
        control._db.commit()

        def fail_agent_tasks(_task_id):
            raise RuntimeError("adapter crashed")

        original_agent_tasks = control._agent_tasks
        control._agent_tasks = fail_agent_tasks
        try:
            control._run_task(completed["task_id"])
        finally:
            control._agent_tasks = original_agent_tasks

        failed = control.get_task(completed["task_id"])
        self.assertEqual(failed["status"], "failed")
        self.assertIn(
            "task.failed",
            [event["type"] for event in control.events(completed["task_id"])],
        )

        class AliveThread:
            def is_alive(self):
                return True

        control._threads["already-running"] = AliveThread()
        control._ensure_runner("already-running")

    def test_plan_optional_path(self):
        control = V2ControlPlane(self.tmp_path())
        task = control.create_task({"goal": "Delete plan for fallback"}, principal="user_1")
        control._db.execute("DELETE FROM v2_plans WHERE task_id = ?", (task["task_id"],))
        control._db.commit()

        self.assertIsNone(control.get_task(task["task_id"])["plan"])

    def tmp_path(self):
        import tempfile
        from pathlib import Path

        return Path(tempfile.mkdtemp(prefix="agentflow-v2-test-"))


def restore_env(key: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(key, None)
    else:
        os.environ[key] = value


class CaptureHandler(BaseHTTPRequestHandler):
    posts: list[dict] = []

    def do_POST(self):
        import json

        length = int(self.headers.get("content-length", "0") or "0")
        body = self.rfile.read(length)
        self.__class__.posts.append(
            {
                "path": self.path,
                "body": json.loads(body.decode("utf-8")),
            }
        )
        self.send_response(200)
        self.send_header("content-length", "2")
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *_args):
        return


class capture_http_posts:
    def __enter__(self):
        CaptureHandler.posts = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), CaptureHandler)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address
        return {"url": f"http://{host}:{port}/bot", "posts": CaptureHandler.posts}

    def __exit__(self, *_args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=1)


if __name__ == "__main__":
    unittest.main()
