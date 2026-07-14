#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any


def main() -> int:
    args = parse_args()
    if args.base_url:
        result = smoke_http(args)
    else:
        result = smoke_direct(args)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


def smoke_direct(args: argparse.Namespace) -> dict[str, Any]:
    from cloud_agents_runtime.v2_control_plane import V2ControlPlane

    root = Path(args.artifact_root or tempfile.mkdtemp(prefix="agentflow-v2-smoke-"))
    control = V2ControlPlane(root)
    task = control.create_task(
        {
            "goal": args.goal,
            "mode": args.mode,
            "channel": "ci",
            "adapter": "fake",
            "metadata": {"smoke": True},
        },
        principal="ci-smoke",
        idempotency_key="ci-v2-smoke",
    )
    task = wait_for(lambda: control.get_task(task["task_id"]), args.timeout)
    assert_task_completed(task)
    overview = control.admin_overview()
    assert overview["tasks"]["total"] >= 1
    return {
        "mode": "direct",
        "task_id": task["task_id"],
        "status": task["status"],
        "strategy": task["plan"]["strategy"],
        "event_count": len(control.events(task["task_id"])),
        "artifact_root": str(root),
    }


def smoke_http(args: argparse.Namespace) -> dict[str, Any]:
    client = HttpClient(args.base_url.rstrip("/"))
    if args.email and args.password:
        client.login(args.email, args.password)
    task = client.post(
        "/v2/tasks",
        {
            "goal": args.goal,
            "mode": args.mode,
            "channel": "smoke",
            "adapter": "fake",
            "metadata": {"smoke": True},
        },
        headers={"Idempotency-Key": "http-v2-smoke"},
    )
    task_id = task["task_id"]
    task = wait_for(lambda: client.get(f"/v2/tasks/{task_id}"), args.timeout)
    assert_task_completed(task)
    overview = client.get("/v2/admin/overview")
    assert overview["tasks"]["total"] >= 1
    return {
        "mode": "http",
        "task_id": task_id,
        "status": task["status"],
        "strategy": task["plan"]["strategy"],
        "event_count": len(client.get(f"/v2/tasks/{task_id}/events.json")["events"]),
    }


def wait_for(fetch: Any, timeout: int) -> dict[str, Any]:
    deadline = time.time() + timeout
    last: dict[str, Any] | None = None
    while time.time() < deadline:
        last = fetch()
        if last.get("status") == "completed":
            return last
        if last.get("status") in {"failed", "cancelled"}:
            raise RuntimeError(f"task ended as {last['status']}: {last}")
        time.sleep(0.1)
    raise TimeoutError(f"task did not complete within {timeout}s: {last}")


def assert_task_completed(task: dict[str, Any]) -> None:
    if task["status"] != "completed":
        raise RuntimeError(f"expected completed task, got {task['status']}")
    if task["progress"]["percent"] != 100:
        raise RuntimeError(f"expected 100% progress, got {task['progress']}")
    if not task.get("result"):
        raise RuntimeError("expected task result")
    if not task.get("plan", {}).get("agent_tasks"):
        raise RuntimeError("expected plan agent tasks")


class HttpClient:
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.cookies = CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookies)
        )

    def login(self, email: str, password: str) -> None:
        result = self.post("/auth/login", {"email": email, "password": password})
        if not result.get("authenticated"):
            raise RuntimeError("login did not authenticate")

    def get(self, path: str) -> dict[str, Any]:
        request = urllib.request.Request(self.base_url + path)
        return self._json(request)

    def post(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + path,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                **(headers or {}),
            },
        )
        return self._json(request)

    def _json(self, request: urllib.request.Request) -> dict[str, Any]:
        try:
            with self.opener.open(request, timeout=10) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{request.full_url} returned {exc.code}: {body}") from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke test V2 control plane")
    parser.add_argument("--base-url", help="runtime base URL; omit for direct mode")
    parser.add_argument("--email", help="login email for HTTP mode")
    parser.add_argument("--password", help="login password for HTTP mode")
    parser.add_argument("--artifact-root", help="direct mode artifact root")
    parser.add_argument(
        "--goal",
        default="Run V2 control-plane smoke with plan, events, and result",
    )
    parser.add_argument(
        "--mode",
        default="multi-agent",
        choices=["auto", "workflow", "multi-agent"],
    )
    parser.add_argument("--timeout", type=int, default=10)
    return parser.parse_args()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"v2 smoke failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
