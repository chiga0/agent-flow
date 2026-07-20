#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any


class Client:
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip("/")
        self.token = token

    def request(
        self, path: str, *, method: str = "GET", payload: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        body = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(
            self.base_url + path,
            data=body,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                **(headers or {}),
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                result = json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            raise RuntimeError(f"{method} {path}: HTTP {exc.code}: {detail}") from exc
        if not isinstance(result, dict):
            raise RuntimeError(f"{method} {path}: expected JSON object")
        return result


def create_and_wait(client: Client, index: int, timeout: float) -> tuple[float, str]:
    started = time.monotonic()
    task = client.request(
        "/v2/tasks",
        method="POST",
        payload={"goal": f"HA load probe {index}", "adapter": "fake"},
        headers={"Idempotency-Key": f"ha-load-{index}-{time.time_ns()}"},
    )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = client.request(f"/v2/tasks/{task['task_id']}")
        if current["status"] == "completed":
            return time.monotonic() - started, str(task["task_id"])
        if current["status"] in {"failed", "cancelled"}:
            raise RuntimeError(f"task {task['task_id']} ended {current['status']}")
        time.sleep(0.05)
    raise TimeoutError(f"task {task['task_id']} exceeded {timeout}s")


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * fraction))]


def run(args: argparse.Namespace) -> dict[str, Any]:
    client = Client(args.base_url, args.token)
    health = client.request("/health")
    ha = client.request("/v2/admin/ha")
    started = time.monotonic()
    latencies: list[float] = []
    task_ids: list[str] = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = [pool.submit(create_and_wait, client, i, args.timeout) for i in range(args.tasks)]
        for future in as_completed(futures):
            latency, task_id = future.result()
            latencies.append(latency)
            task_ids.append(task_id)
    duration = time.monotonic() - started
    if not client.request("/health").get("ok"):
        raise RuntimeError("health check failed after load")
    return {
        "status": "passed",
        "health": health,
        "ha": ha,
        "tasks": len(task_ids),
        "concurrency": args.concurrency,
        "duration_seconds": round(duration, 3),
        "throughput_tasks_per_second": round(len(task_ids) / max(duration, 0.001), 2),
        "latency_seconds": {
            "mean": round(statistics.mean(latencies), 3),
            "p50": round(percentile(latencies, 0.50), 3),
            "p95": round(percentile(latencies, 0.95), 3),
            "max": round(max(latencies), 3),
        },
        "task_ids": task_ids,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate aflow HA health under concurrent V2 load"
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--token", required=True)
    parser.add_argument("--tasks", type=int, default=20)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args()
    if args.tasks < 1 or args.concurrency < 1:
        parser.error("--tasks and --concurrency must be positive")
    return args


if __name__ == "__main__":
    try:
        print(json.dumps(run(parse_args()), ensure_ascii=False, indent=2))
    except Exception as exc:
        print(f"HA load validation failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
