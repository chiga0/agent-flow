from __future__ import annotations

import os
import unittest
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from unittest import mock

from runtime.cloud_agents_runtime.v2_control_plane import (
    V2ControlPlane,
    extract_feishu_text,
    failure_summary,
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
            streamed = [
                event
                for event in control.events(task["task_id"])
                if event["type"] == "agent.message"
                and event["payload"].get("agent_task_id") == "at_test"
            ]
            self.assertTrue(streamed)
            self.assertTrue(streamed[-1]["payload"]["partial"])
            script.write_text(
                "#!/bin/sh\ncat >/dev/null\nprintf '\\nfailed output\\n'\nexit 2\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "exited with code 2"):
                control._execute_agent_adapter(task["task_id"], agent)
            with mock.patch(
                "runtime.cloud_agents_runtime.v2_control_plane.subprocess.Popen",
                side_effect=OSError("boom"),
            ):
                failed = control._execute_agent_adapter(task["task_id"], agent)
            self.assertEqual(failed["execution_mode"], "cli-error")
        finally:
            restore_env("V2_ENABLE_REAL_CLI_ADAPTERS", old_enabled)
            restore_env("V2_CODEX_CLI_COMMAND", old_command)

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
                    "message": "Accepted by aflow",
                },
            )
            messages = control.channel_messages("feishu")

            self.assertTrue(inbound["accepted"])
            self.assertEqual(inbound["message"]["direction"], "inbound")
            self.assertEqual(outbound["status"], "sent")
            self.assertEqual(len(sink["posts"]), 1)
            self.assertEqual(
                sink["posts"][0]["body"]["content"]["text"],
                "Accepted by aflow",
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
        agent_event = next(
            event
            for event in events
            if event["_meta"]["runtimeEventType"] == "agent.message"
        )
        self.assertTrue(agent_event["_meta"]["agentTaskId"])
        self.assertIn(
            agent_event["_meta"]["agentRole"],
            {"agent", "brain", "builder", "reviewer"},
        )
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
        self.assertEqual(failed["result"]["failure"]["category"], "adapter")
        self.assertIn("next_action", failed["result"]["failure"])
        self.assertIn(
            "task.failed",
            [event["type"] for event in control.events(completed["task_id"])],
        )

        class AliveThread:
            def is_alive(self):
                return True

        control._threads["already-running"] = AliveThread()
        control._ensure_runner("already-running")

    def test_project_membership_artifact_access_and_audit_bundle(self):
        control = V2ControlPlane(self.tmp_path())
        project = control.upsert_project(
            {"project_id": "project_team", "name": "Team"},
            principal="owner@example.com",
        )
        member = control.upsert_project_member(
            project["project_id"],
            {"email": "viewer@example.com", "role": "viewer"},
        )
        task = control.create_task(
            {"goal": "Shared project task", "project_id": project["project_id"]},
            principal="owner@example.com",
        )
        completed = wait_for_status(control, task["task_id"], "completed")

        self.assertEqual(member["role"], "viewer")
        self.assertTrue(
            control.can_access_task(task["task_id"], "viewer@example.com", ["member"])
        )
        self.assertFalse(
            control.can_access_task(
                task["task_id"], "viewer@example.com", ["member"], write=True
            )
        )
        self.assertFalse(
            control.can_access_task(task["task_id"], "stranger@example.com", ["member"])
        )
        self.assertEqual(
            [item["task_id"] for item in control.list_tasks(
                principal="viewer@example.com", roles=["member"]
            )],
            [task["task_id"]],
        )
        artifact = control.artifacts(task["task_id"])[0]
        self.assertEqual(
            control.artifact(task["task_id"], artifact["artifact_id"])["artifact_id"],
            artifact["artifact_id"],
        )
        audit = control.audit_bundle(task["task_id"])
        self.assertEqual(audit["schema"], "agentflow-v2-task-audit/v1")
        self.assertEqual(completed["execution_mode"], "fake")

    def test_temporal_dispatch_records_external_workflow(self):
        control = V2ControlPlane(self.tmp_path())
        task = control.create_task({"goal": "Temporal dispatch"}, principal="user_1")
        completed = wait_for_status(control, task["task_id"], "completed")
        with mock.patch(
            "runtime.cloud_agents_runtime.temporal_bridge.start_task_workflow",
            new=mock.AsyncMock(return_value=f"agentflow-v2-{completed['task_id']}"),
        ):
            control._dispatch_temporal_task(completed["task_id"])
        dispatched = [
            event
            for event in control.events(completed["task_id"])
            if event["type"] == "workflow.temporal_dispatched"
        ]
        self.assertEqual(len(dispatched), 1)
        self.assertEqual(
            dispatched[0]["payload"]["workflow_id"],
            f"agentflow-v2-{completed['task_id']}",
        )

    def test_temporal_dispatch_failure_and_execute_now_boundaries(self):
        control = V2ControlPlane(self.tmp_path())
        task = control.create_task({"goal": "Temporal failure"}, principal="user_1")
        completed = wait_for_status(control, task["task_id"], "completed")
        with mock.patch(
            "runtime.cloud_agents_runtime.temporal_bridge.start_task_workflow",
            new=mock.AsyncMock(side_effect=RuntimeError("Temporal timeout")),
        ):
            control._dispatch_temporal_task(completed["task_id"])
        self.assertEqual(control.get_task(completed["task_id"])["status"], "failed")
        self.assertEqual(
            control.events(completed["task_id"])[-2]["type"],
            "workflow.temporal_dispatch_failed",
        )
        with self.assertRaises(KeyError):
            control.execute_task_now("missing")

    def test_project_access_and_failure_summary_boundaries(self):
        control = V2ControlPlane(self.tmp_path())
        with self.assertRaises(ValueError):
            control.upsert_project(
                {"project_id": " ", "tenant_id": "tenant_default"},
                principal="owner@example.com",
            )
        with self.assertRaises(ValueError):
            control.upsert_project_member(
                "project_default", {"user_id": "user@example.com", "role": "invalid"}
            )
        with self.assertRaises(KeyError):
            control.upsert_project_member(
                "missing", {"user_id": "user@example.com", "role": "viewer"}
            )
        with self.assertRaises(KeyError):
            control.can_access_project("missing", "user@example.com", ["member"])
        self.assertTrue(
            control.can_access_project(
                "project_default", "new@example.com", ["member"], write=True
            )
        )
        member = control.upsert_project_member(
            "project_default",
            {"user_id": "off@example.com", "role": "viewer", "status": "disabled"},
        )
        self.assertEqual(member["status"], "disabled")
        self.assertFalse(
            control.can_access_project(
                "project_default", "off@example.com", ["member"], write=False
            )
        )
        self.assertEqual(failure_summary(TimeoutError("timeout"))["category"], "timeout")
        self.assertEqual(
            failure_summary(PermissionError("permission denied"))["category"],
            "permission",
        )
        self.assertEqual(failure_summary(RuntimeError())["category"], "runtime")

    def test_plan_optional_path(self):
        control = V2ControlPlane(self.tmp_path())
        task = control.create_task({"goal": "Delete plan for fallback"}, principal="user_1")
        with control._lock:
            control._db.execute(
                "DELETE FROM v2_plans WHERE task_id = ?", (task["task_id"],)
            )
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
