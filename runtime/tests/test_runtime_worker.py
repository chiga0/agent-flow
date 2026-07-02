from __future__ import annotations

import tempfile
import time
import unittest
import urllib.parse
from pathlib import Path

from runtime.cloud_agents_runtime.worker import (
    RemoteWorkerConfig,
    RemoteWorkerDaemon,
    main as worker_main,
)
from runtime.tests.test_runtime_server import request_json, running_runtime


class RemoteWorkerDaemonTest(unittest.TestCase):
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

    def test_remote_worker_cli_help(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            worker_main(["--help"])
        self.assertEqual(ctx.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
