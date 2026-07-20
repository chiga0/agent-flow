#!/usr/bin/env python3
from __future__ import annotations

import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from runtime.cloud_agents_runtime.v2_control_plane import V2ControlPlane


def main() -> int:
    if not os.environ.get("V2_DATABASE_URL"):
        raise SystemExit("V2_DATABASE_URL is required")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        first = V2ControlPlane(root / "first")
        second = V2ControlPlane(root / "second")
        worker_id = "postgres-smoke-worker"
        first.heartbeat_execution_worker(worker_id, {"adapters": ["fake"]})
        task = first.create_task(
            {"goal": "verify shared postgres task state", "adapter": "fake"},
            principal="ci@example.com",
        )
        if second.get_task(task["task_id"])["task_id"] != task["task_id"]:
            raise RuntimeError("second control plane cannot read shared task")

        def claim(control: V2ControlPlane) -> dict[str, object]:
            return control.claim_remote_agent_task(worker_id, {"adapters": ["fake"]})

        with ThreadPoolExecutor(max_workers=2) as pool:
            claims = list(pool.map(claim, (first, second)))
        assignments = [claim["assignment"] for claim in claims if claim.get("assignment")]
        if len(assignments) != 1:
            raise RuntimeError(f"expected one lease winner, got {len(assignments)}")
        assignment = assignments[0]
        if not isinstance(assignment, dict):
            raise RuntimeError("invalid assignment")
        second.complete_remote_agent_task(
            worker_id,
            str(assignment["agent_task_id"]),
            {
                "lease_token": assignment["lease_token"],
                "summary": "postgres shared-state smoke passed",
                "execution_mode": "fake",
            },
        )
        completed = first.get_task(task["task_id"])
        if completed["status"] != "completed":
            raise RuntimeError(f"shared task did not complete: {completed['status']}")
        first._db.close()
        second._db.close()
    print("postgres v2 multi-control-plane smoke: passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
