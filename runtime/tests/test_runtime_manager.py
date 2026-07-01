from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from runtime.cloud_agents_runtime.adapters.fake import FakeAdapter
from runtime.cloud_agents_runtime.manager import RunManager, positive_int
from runtime.cloud_agents_runtime.models import RunSpec
from runtime.cloud_agents_runtime.store import RunStore, utc_now_plus


class RunManagerTest(unittest.TestCase):
    def test_fake_run_completes_and_writes_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = RunManager(Path(tmp))
            try:
                run = manager.create_run(RunSpec(prompt="hello runtime", adapter="fake"))

                deadline = time.time() + 2
                while time.time() < deadline:
                    current = manager.get_run(run.run_id)
                    if current and current.status == "completed":
                        break
                    time.sleep(0.02)

                current = manager.get_run(run.run_id)
                self.assertIsNotNone(current)
                self.assertEqual(current.status, "completed")
                events = manager.store.events_since(run.run_id)
                self.assertEqual(events[0].type, "run.created")
                self.assertTrue(any(event.type == "message.delta" for event in events))
                self.assertTrue((Path(tmp) / run.run_id / "events.jsonl").exists())
                self.assertTrue((Path(tmp) / run.run_id / "raw_events.jsonl").exists())
                self.assertTrue((Path(tmp) / run.run_id / "final_1.json").exists())
            finally:
                manager.shutdown()

    def test_unknown_adapter_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = RunManager(Path(tmp))
            try:
                with self.assertRaises(ValueError):
                    manager.create_run(RunSpec(prompt="x", adapter="missing"))
            finally:
                manager.shutdown()

    def test_cancel_terminal_run_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = RunManager(Path(tmp))
            try:
                run = manager.create_run(RunSpec(prompt="short", adapter="fake"))

                deadline = time.time() + 2
                while time.time() < deadline and manager.get_run(run.run_id).status != "completed":
                    time.sleep(0.02)

                manager.cancel(run.run_id, "too late")
                events = manager.store.events_since(run.run_id)
                self.assertEqual(events[-1].type, "cancel.ignored")
            finally:
                manager.shutdown()

    def test_store_persists_runs_events_and_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager = RunManager(root)
            try:
                run = manager.create_run(RunSpec(prompt="persist me", adapter="fake"))
                self.wait_for_status(manager, run.run_id, "completed")
            finally:
                manager.shutdown()

            self.assertTrue((root / "runtime.db").exists())
            self.assertTrue((root / run.run_id / "diagnostics.json").exists())

            restored = RunManager(root)
            try:
                restored_run = restored.get_run(run.run_id)
                self.assertIsNotNone(restored_run)
                self.assertEqual(restored_run.status, "completed")
                events = restored.store.events_since(run.run_id)
                self.assertEqual(events[0].type, "run.created")
                self.assertEqual(events[-1].type, "run.completed")
            finally:
                restored.shutdown()

    def test_replay_cli_rebuilds_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager = RunManager(root)
            try:
                run = manager.create_run(RunSpec(prompt="replay me", adapter="fake"))
                self.wait_for_status(manager, run.run_id, "completed")
            finally:
                manager.shutdown()

            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/replay_run.py",
                    "--artifact-root",
                    str(root),
                    "--run-id",
                    run.run_id,
                    "--format",
                    "state",
                ],
                check=True,
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                text=True,
            )
            state = json.loads(result.stdout)
            self.assertEqual(state["status"], "completed")
            self.assertEqual(state["last_event"], "run.completed")

    def test_permission_resolution_rejects_bad_decision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = RunManager(Path(tmp))
            try:
                run = manager.create_run(RunSpec(adapter="fake"))
                with self.assertRaises(ValueError):
                    manager.resolve_permission(run.run_id, "perm-1", {"decision": "maybe"})
            finally:
                manager.shutdown()

    def test_queue_respects_worker_capacity_and_releases_next_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = RunManager(
                Path(tmp),
                adapters={"fake": FakeAdapter(delay_seconds=0.05)},
                worker_capacity=1,
                worker_id="unit-worker",
            )
            try:
                first = manager.create_run(
                    RunSpec(
                        prompt=(
                            "one two three four five six seven eight nine ten "
                            "eleven twelve thirteen fourteen fifteen sixteen"
                        ),
                        adapter="fake",
                    )
                )
                second = manager.create_run(
                    RunSpec(
                        prompt="alpha beta gamma delta epsilon zeta eta theta",
                        adapter="fake",
                    )
                )
                self.wait_for_status_pair(
                    manager,
                    first.run_id,
                    "running",
                    second.run_id,
                    "queued",
                )

                snapshot = manager.queue_status()
                self.assertEqual(snapshot["counts"]["running"], 1)
                self.assertEqual(snapshot["counts"]["queued"], 1)
                self.assertEqual(snapshot["workers"][0]["capacity"], 1)
                self.assertEqual(snapshot["workers"][0]["active_count"], 1)

                self.wait_for_status(manager, first.run_id, "completed")
                self.wait_for_status(manager, second.run_id, "completed")
                second_events = [event.type for event in manager.store.events_since(second.run_id)]
                self.assertIn("run.queued", second_events)
                self.assertIn("lease.claimed", second_events)
            finally:
                manager.shutdown()

    def test_capacity_zero_keeps_run_queued_and_allows_cancel(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = RunManager(Path(tmp), worker_capacity=0, worker_id="paused-worker")
            try:
                run = manager.create_run(RunSpec(prompt="wait in queue", adapter="fake"))
                self.assertEqual(manager.get_run(run.run_id).status, "queued")
                self.assertEqual(manager.queue_status()["counts"]["queued"], 1)

                manager.send_input(run.run_id, "too early")
                self.assertIn(
                    "input.rejected",
                    [event.type for event in manager.store.events_since(run.run_id)],
                )
                manager.cancel(run.run_id, "operator pause")
                self.assertEqual(manager.get_run(run.run_id).status, "cancelled")
                manager.shutdown()
                manager.shutdown()
            finally:
                manager.shutdown()

    def test_send_input_to_running_run_uses_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = RunManager(
                Path(tmp),
                adapters={"fake": FakeAdapter(delay_seconds=0.01)},
                worker_id="input-worker",
            )
            try:
                run = manager.create_run(RunSpec(adapter="fake"))
                self.wait_for_status(manager, run.run_id, "running")
                manager.send_input(run.run_id, "manual prompt")
                self.wait_for_status(manager, run.run_id, "completed")
                events = [event.type for event in manager.store.events_since(run.run_id)]
                self.assertIn("input.accepted", events)
            finally:
                manager.shutdown()

    def test_expired_lease_is_recovered_to_queue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = RunStore(Path(tmp))
            try:
                run = store.create_run(RunSpec(adapter="fake"))
                store.enqueue_run(run.run_id)
                store.register_worker("dead-worker", capacity=1, lease_ttl_seconds=1)
                job = store.claim_next_job("dead-worker", lease_ttl_seconds=30)
                self.assertIsNotNone(job)
                self.assertIsNone(store.claim_next_job("dead-worker", lease_ttl_seconds=30))
                self.assertEqual(store.queued_job_count(), 0)
                worker = store.heartbeat_worker(
                    "dead-worker",
                    capacity=1,
                    lease_ttl_seconds=30,
                )
                self.assertEqual(worker.active_count, 1)
                store._jobs[run.run_id].lease_expires_at = utc_now_plus(-1)
                store._persist_job(store._jobs[run.run_id])

                recovered = store.recover_expired_leases()
                self.assertEqual(recovered, [run.run_id])
                snapshot = store.queue_snapshot()
                self.assertEqual(snapshot["counts"]["queued"], 1)
                self.assertIn(
                    "lease.expired",
                    [event.type for event in store.events_since(run.run_id)],
                )
            finally:
                store.close()

    def test_positive_int_parsing(self) -> None:
        self.assertEqual(positive_int(None, "3", default=1), 3)
        self.assertEqual(positive_int(None, "bad", default=2), 2)
        self.assertEqual(positive_int(-1, None, default=2), 0)

    def wait_for_status(self, manager: RunManager, run_id: str, status: str) -> None:
        deadline = time.time() + 2
        while time.time() < deadline:
            current = manager.get_run(run_id)
            if current and current.status == status:
                return
            time.sleep(0.02)
        self.fail(f"run {run_id} did not reach {status}")

    def wait_for_status_pair(
        self,
        manager: RunManager,
        first_run_id: str,
        first_status: str,
        second_run_id: str,
        second_status: str,
    ) -> None:
        deadline = time.time() + 2
        while time.time() < deadline:
            first = manager.get_run(first_run_id)
            second = manager.get_run(second_run_id)
            if first and second and first.status == first_status and second.status == second_status:
                return
            time.sleep(0.02)
        self.fail(
            f"runs did not reach {first_status}/{second_status}: "
            f"{manager.get_run(first_run_id)} / {manager.get_run(second_run_id)}"
        )


if __name__ == "__main__":
    unittest.main()
