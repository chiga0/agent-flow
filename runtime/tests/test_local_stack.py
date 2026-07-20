from __future__ import annotations

import argparse
import importlib.util
import os
import stat
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "local_stack.py"
SPEC = importlib.util.spec_from_file_location("local_stack", SCRIPT)
assert SPEC and SPEC.loader
local_stack = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(local_stack)


class LocalStackTest(unittest.TestCase):
    def test_init_is_private_and_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env.local"
            with mock.patch.object(local_stack, "DEFAULT_DATA_DIR", Path(directory) / "data"):
                first = local_stack.init_environment(env_file, bind="127.0.0.1")
                original = env_file.read_text(encoding="utf-8")
                second = local_stack.init_environment(env_file, bind="0.0.0.0")

            self.assertEqual(first, second)
            self.assertEqual(env_file.read_text(encoding="utf-8"), original)
            self.assertEqual(stat.S_IMODE(env_file.stat().st_mode), 0o600)
            self.assertEqual(first["RUNTIME_BIND"], "127.0.0.1")
            self.assertNotIn(first["RUNTIME_BOOTSTRAP_PASSWORD"], "captured console output")

    def test_init_rejects_unsafe_or_invalid_bind(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env.local"
            with self.assertRaises(local_stack.StackError):
                local_stack.init_environment(path, bind="192.168.1.10")

    def test_existing_incomplete_environment_fails_with_required_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env.local"
            path.write_text("RUN_MANAGER_TOKEN=token\n", encoding="utf-8")

            with self.assertRaisesRegex(local_stack.StackError, "RUNTIME_ARTIFACTS_DIR"):
                local_stack.init_environment(path, bind="127.0.0.1")

    def test_validate_demo_accepts_complete_multi_agent_evidence(self):
        task = {
            "status": "completed",
            "plan": {
                "strategy": "orchestrator-workers",
                "agent_tasks": [
                    {"role": "brain"},
                    {"role": "builder"},
                    {"role": "reviewer"},
                ],
            },
            "metadata": {"dispatch": {"execution_unit_id": "test-runtime"}},
        }
        events = [
            {"type": "agent.message", "actor": role}
            for role in ("brain", "builder", "reviewer")
        ]
        webshell = [
            {"_meta": {"agentRole": role}}
            for role in ("brain", "builder", "reviewer")
        ]
        artifacts = [
            {"content": {"adapter": {"execution_mode": "real-cli"}}}
            for _ in range(3)
        ]
        evidence = {
            "events": events,
            "webshell": webshell,
            "artifacts": artifacts,
            "evaluations": [{"status": "passed"}] * 3,
            "audit": {"schema": "agentflow-v2-task-audit/v1"},
        }

        local_stack.validate_demo(
            task,
            evidence,
            {"V2_LOCAL_EXECUTION_UNIT_ID": "test-runtime"},
            require_real_cli=True,
        )

    def test_validate_demo_reports_missing_live_role(self):
        task = {
            "status": "completed",
            "plan": {
                "strategy": "orchestrator-workers",
                "agent_tasks": [
                    {"role": "brain"},
                    {"role": "builder"},
                    {"role": "reviewer"},
                ],
            },
            "metadata": {"dispatch": {"execution_unit_id": "test-runtime"}},
        }
        evidence = {
            "events": [{"type": "agent.message", "actor": "brain"}],
            "webshell": [{"_meta": {"agentRole": "brain"}}],
            "artifacts": [{}, {}, {}],
            "evaluations": [{"status": "passed"}],
            "audit": {"schema": "agentflow-v2-task-audit/v1"},
        }

        with self.assertRaisesRegex(local_stack.StackError, "live output for all roles"):
            local_stack.validate_demo(
                task,
                evidence,
                {"V2_LOCAL_EXECUTION_UNIT_ID": "test-runtime"},
                require_real_cli=False,
            )

    def test_api_request_wraps_transient_connection_reset(self):
        with mock.patch.object(
            urllib.request,
            "urlopen",
            side_effect=ConnectionResetError("peer reset"),
        ):
            with self.assertRaisesRegex(local_stack.StackError, "peer reset"):
                local_stack.api_request({"RUN_MANAGER_TOKEN": "token"}, "/health")

    def test_down_without_environment_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            local_stack, "parse_args"
        ) as parse_args, mock.patch.object(local_stack, "compose") as compose:
            parse_args.return_value = argparse.Namespace(
                command="down",
                env_file=Path(directory) / ".env.local",
            )

            self.assertEqual(local_stack.main(), 0)
            compose.assert_not_called()


class LocalExecutionUnitEnvironmentTest(unittest.TestCase):
    def test_environment_configures_seeded_execution_unit(self):
        from runtime.cloud_agents_runtime.v2_control_plane import V2ControlPlane

        env = {
            "V2_LOCAL_EXECUTION_UNIT_ID": "nas-runtime",
            "V2_LOCAL_EXECUTION_UNIT_KIND": "co-located-runtime",
            "V2_LOCAL_EXECUTION_UNIT_LABELS_JSON": '{"host":"nas"}',
            "V2_LOCAL_EXECUTION_UNIT_RESOURCES_JSON": '{"cpu":4,"memory_mb":8192}',
            "V2_LOCAL_EXECUTION_UNIT_ADAPTERS": "fake,codex",
            "V2_LOCAL_EXECUTION_UNIT_FEATURES": "workspace,events",
        }
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(
            os.environ, env, clear=False
        ):
            control = V2ControlPlane(Path(directory))
            units = control.execution_units()
            control._db.close()

        unit = next(item for item in units if item["unit_id"] == "nas-runtime")
        self.assertEqual(unit["kind"], "co-located-runtime")
        self.assertEqual(unit["labels"]["execution_location"], "co-located-runtime")
        self.assertEqual(unit["resources"]["memory_mb"], 8192)
        self.assertEqual(unit["adapters"], ["fake", "codex"])

    def test_invalid_execution_unit_json_fails_fast(self):
        from runtime.cloud_agents_runtime.v2_control_plane import V2ControlPlane

        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(
            os.environ,
            {"V2_LOCAL_EXECUTION_UNIT_LABELS_JSON": "[]"},
            clear=False,
        ):
            with self.assertRaisesRegex(ValueError, "must contain a JSON object"):
                V2ControlPlane(Path(directory))

    def test_unsupported_execution_unit_adapter_fails_fast(self):
        from runtime.cloud_agents_runtime.v2_control_plane import V2ControlPlane

        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(
            os.environ,
            {"V2_LOCAL_EXECUTION_UNIT_ADAPTERS": "fake,typo"},
            clear=False,
        ):
            with self.assertRaisesRegex(ValueError, "unsupported.*typo"):
                V2ControlPlane(Path(directory))

    def test_configured_unit_replaces_legacy_seed_on_upgrade(self):
        from runtime.cloud_agents_runtime.v2_control_plane import V2ControlPlane

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy = V2ControlPlane(root)
            legacy._db.execute(
                "UPDATE v2_execution_units SET labels_json = ? WHERE unit_id = ?",
                ('{"region": "local", "tier": "dev"}', "local-dev"),
            )
            legacy._db.commit()
            legacy._db.close()
            with mock.patch.dict(
                os.environ,
                {"V2_LOCAL_EXECUTION_UNIT_ID": "upgraded-runtime"},
                clear=False,
            ):
                upgraded = V2ControlPlane(root)
                unit_ids = {unit["unit_id"] for unit in upgraded.execution_units()}
                upgraded._db.close()

        self.assertIn("upgraded-runtime", unit_ids)
        self.assertNotIn("local-dev", unit_ids)


if __name__ == "__main__":
    unittest.main()
