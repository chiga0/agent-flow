from __future__ import annotations

import argparse
import unittest
from unittest.mock import patch

from scripts.validate_qwen_mission import main, validate_single_run


class ValidateQwenMissionTest(unittest.TestCase):
    def test_main_single_run_acceptance_does_not_create_mission_by_default(self) -> None:
        client = CompletedRunClient()
        with patch("scripts.validate_qwen_mission.Client", return_value=client):
            self.assertEqual(
                main(
                    [
                        "--base-url",
                        "http://runtime.test",
                        "--token",
                        "token",
                        "--timeout",
                        "60",
                        "--validate-single-run",
                        "--expect-executor-strategy",
                        "per_run_process",
                    ]
                ),
                0,
            )

        self.assertIn(("POST", "/runs", client.run_payload), client.calls)
        self.assertNotIn("POST /missions", client.method_paths())

    def test_single_run_timeout_cancels_run_and_prints_diagnostics(self) -> None:
        client = RecordingClient()
        args = argparse.Namespace(timeout=10.0, expect_executor_strategy=None)

        with (
            patch(
                "scripts.validate_qwen_mission.now",
                side_effect=[0.0, 0.0, 11.0],
            ),
            patch("scripts.validate_qwen_mission.sleep_for"),
        ):
            self.assertFalse(validate_single_run(client, args, deadline=10.0))

        self.assertIn(
            (
                "POST",
                "/runs/run-timeout/cancel",
                {"reason": "qwen acceptance timeout"},
            ),
            client.calls,
        )
        self.assertIn(("GET", "/queue", None), client.calls)
        self.assertIn(("GET", "/executors", None), client.calls)
        self.assertIn(("GET", "/runs/run-timeout/events.json", None), client.calls)
        self.assertIn(("GET", "/runs/run-timeout/executor", None), client.calls)


class CompletedRunClient:
    def __init__(self) -> None:
        self.run_payload: dict[str, object] | None = None
        self.calls: list[tuple[str, str, dict[str, object] | None]] = []

    def method_paths(self) -> list[str]:
        return [f"{method} {path}" for method, path, _payload in self.calls]

    def post(self, path: str, payload: dict[str, object]) -> dict[str, object]:
        self.calls.append(("POST", path, payload))
        if path == "/runs":
            self.run_payload = payload
            return {"run_id": "run-ok", "status": "queued"}
        raise AssertionError(f"unexpected post: {path}")

    def get(self, path: str) -> dict[str, object]:
        self.calls.append(("GET", path, None))
        if path == "/health":
            return {"ok": True}
        if path == "/capabilities":
            return {
                "adapters": {"qwen": {}, "fake": {}},
                "executor_registry": {"config": {"strategy": "per_run_process"}},
            }
        if path == "/queue":
            return {"counts": {"completed": 1}}
        if path == "/executors":
            return {"executor_registry": {"config": {"strategy": "per_run_process"}}}
        if path == "/access/policy":
            return {"mode": "single-tenant-rbac-foundation"}
        if path == "/cost/status":
            return {"status": "unconfigured"}
        if path == "/runs/run-ok":
            return {"run_id": "run-ok", "status": "completed"}
        if path == "/runs/run-ok/events.json":
            return {"events": [{"type": "run.completed"}]}
        if path == "/runs/run-ok/artifacts":
            return {
                "artifacts": [
                    {"name": "events.jsonl"},
                    {"name": "raw_events.jsonl"},
                    {"name": "diagnostics.json"},
                    {"name": "cost.json"},
                ]
            }
        if path == "/runs/run-ok/executor":
            return {"executor": {"strategy": "per_run_process"}}
        raise AssertionError(f"unexpected get: {path}")


class RecordingClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, object] | None]] = []

    def post(self, path: str, payload: dict[str, object]) -> dict[str, object]:
        self.calls.append(("POST", path, payload))
        if path == "/runs":
            return {"run_id": "run-timeout", "status": "queued"}
        if path == "/runs/run-timeout/cancel":
            return {"cancelled": True}
        raise AssertionError(f"unexpected post: {path}")

    def get(self, path: str) -> dict[str, object]:
        self.calls.append(("GET", path, None))
        if path == "/runs/run-timeout":
            return {"run_id": "run-timeout", "status": "running"}
        if path == "/queue":
            return {"counts": {"running": 1}}
        if path == "/executors":
            return {"executors": []}
        if path == "/runs/run-timeout/events.json":
            return {"events": [{"type": "run.started"}]}
        if path == "/runs/run-timeout/executor":
            return {"executor": {"strategy": "per_run_process"}}
        raise AssertionError(f"unexpected get: {path}")
