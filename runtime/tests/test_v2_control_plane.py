from __future__ import annotations

import os
import unittest
import time
from unittest import mock

from runtime.cloud_agents_runtime.v2_control_plane import V2ControlPlane, json_loads


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
            with mock.patch(
                "runtime.cloud_agents_runtime.v2_control_plane.subprocess.run",
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


if __name__ == "__main__":
    unittest.main()
