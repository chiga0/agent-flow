#!/usr/bin/env python3
"""Run real Client -> remote worker -> Qwen-Code acceptance scenarios."""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any
from uuid import uuid4


TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


class Client:
    def __init__(self, base_url: str, token: str, timeout: int):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def get(self, path: str) -> dict[str, Any]:
        return self.request("GET", path)

    def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.request("POST", path, payload)

    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        idempotency_key = f"remote-e2e-{uuid4().hex}"
        last_error = ""
        for attempt in range(1, 7):
            request = urllib.request.Request(
                self.base_url + path,
                data=body,
                method=method,
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Content-Type": "application/json",
                    "Idempotency-Key": idempotency_key,
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    return json.load(response)
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                last_error = f"HTTP {exc.code}: {detail}"
                if exc.code not in {502, 503, 504}:
                    raise RuntimeError(
                        f"{method} {path} returned {exc.code}: {detail}"
                    ) from exc
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                last_error = str(exc)
            if attempt < 6:
                delay = min(2 ** (attempt - 1), 8)
                print(
                    json.dumps(
                        {
                            "request_retry": f"{method} {path}",
                            "attempt": attempt,
                            "delay_seconds": delay,
                            "error": last_error,
                        },
                        ensure_ascii=False,
                    )
                )
                time.sleep(delay)
        raise RuntimeError(f"{method} {path} failed after retries: {last_error}")


CASES = (
    {
        "name": "code-audit",
        "mode": "single",
        "goal": (
            "对 /opt/agentflow-worker/runtime/cloud_agents_runtime/worker.py 做只读代码审计；"
            "至少指出三个有代码位置依据的可靠性或安全风险，按严重度排序，并给出可执行修复建议。"
            "不要修改任何文件。"
        ),
    },
    {
        "name": "ops-inspection",
        "mode": "single",
        "goal": (
            "对当前 ECS 做只读运维巡检：检查系统负载、可用内存、磁盘、"
            "cloud-agents-worker 与 cloud-agents-qwen 服务状态及 4210 监听地址；"
            "输出证据、风险分级和结论，不要修改系统。"
        ),
    },
    {
        "name": "multi-stage-research",
        "mode": "multi-agent",
        "goal": (
            "完成一项多阶段研究：结合 /opt/agentflow-worker/docs 与 runtime 源码，"
            "分析 AgentFlow 从 SQLite 单机控制面演进到 NAS 主控加两个 ECS 执行单元时的"
            "可靠性、安全边界和容量权衡。先列证据，再比较方案，最后给出分阶段建议；只读。"
        ),
    },
    {
        "name": "file-generation",
        "mode": "single",
        "goal": (
            "生成一份中文 Markdown 交付物到"
            " /var/lib/cloud-agents-worker/workspace/e2e/generated-deliverable.md。"
            "内容必须包含标题、执行单元信息、五项验收清单和生成时间；"
            "写入后重新读取并确认文件非空。不要修改其他文件。"
        ),
    },
)


def create_conversation(
    client: Client,
    *,
    case: dict[str, str],
    unit_id: str,
    round_index: int,
) -> tuple[dict[str, Any], str]:
    conversation = client.post(
        "/conversations",
        {
            "goal": case["goal"],
            "adapter": "qwen",
            "mode": case["mode"],
            "channel": "e2e",
            "metadata": {
                "execution_unit_id": unit_id,
                "e2e_case": case["name"],
                "e2e_round": round_index,
            },
        },
    )
    executions = conversation.get("executions") or []
    if not executions:
        raise RuntimeError("conversation did not create an execution")
    return conversation, str(executions[-1]["task_id"])


def approve_pending_qwen_permissions(
    client: Client,
    task_id: str,
    approved: set[tuple[str, str]],
) -> None:
    for run in client.get("/runs").get("runs", []):
        metadata = dict(run.get("spec", {}).get("metadata") or {})
        if metadata.get("v2_task_id") != task_id:
            continue
        run_id = str(run["run_id"])
        events = client.get(f"/runs/{urllib.parse.quote(run_id)}/events.json").get(
            "events", []
        )
        for event in events:
            if event.get("type") != "permission.requested":
                continue
            data = dict(event.get("data") or {})
            raw = dict(data.get("raw") or {})
            raw_data = dict(raw.get("data") or {})
            permission_id = str(
                data.get("permission_id")
                or data.get("requestId")
                or raw_data.get("requestId")
                or ""
            )
            key = (run_id, permission_id)
            if not permission_id or key in approved:
                continue
            client.post(
                f"/runs/{urllib.parse.quote(run_id)}/permissions/"
                f"{urllib.parse.quote(permission_id)}",
                {"decision": "approve", "reason": "approved by remote E2E suite"},
            )
            approved.add(key)


def wait_for_task(client: Client, task_id: str) -> dict[str, Any]:
    deadline = time.time() + client.timeout
    previous = None
    approved: set[tuple[str, str]] = set()
    while time.time() < deadline:
        task = client.get(f"/v2/tasks/{urllib.parse.quote(task_id)}")
        current = (task.get("status"), task.get("progress", {}).get("percent"))
        if current != previous:
            print(json.dumps({"task_id": task_id, "state": current}, ensure_ascii=False))
            previous = current
        approve_pending_qwen_permissions(client, task_id, approved)
        if task.get("status") in TERMINAL_STATUSES:
            return task
        time.sleep(2)
    raise TimeoutError(f"task {task_id} did not finish within {client.timeout}s")


def assert_remote_result(
    task: dict[str, Any], unit_id: str, worker_id: str
) -> dict[str, Any]:
    if task.get("status") != "completed":
        raise RuntimeError(f"task {task.get('task_id')} ended as {task.get('status')}")
    dispatch = dict(task.get("metadata", {}).get("dispatch") or {})
    if dispatch.get("execution_unit_id") != unit_id:
        raise RuntimeError(f"task dispatch mismatch: {dispatch}")
    agents = task.get("plan", {}).get("agent_tasks") or []
    if not agents:
        raise RuntimeError("task has no agent results")
    remote_runs: list[str] = []
    for agent in agents:
        adapter = dict(agent.get("result", {}).get("adapter") or {})
        if adapter.get("execution_mode") != "remote-worker":
            raise RuntimeError(f"agent did not use remote-worker: {adapter}")
        if adapter.get("execution_unit_id") != unit_id:
            raise RuntimeError(f"agent execution unit mismatch: {adapter}")
        if adapter.get("worker_id") != worker_id:
            raise RuntimeError(f"agent worker mismatch: {adapter}")
        if not adapter.get("success"):
            raise RuntimeError(f"remote Qwen execution failed: {adapter}")
        remote_runs.append(str(adapter.get("remote_run_id") or ""))
    if not all(remote_runs):
        raise RuntimeError("remote run evidence is incomplete")
    return {
        "task_id": task["task_id"],
        "strategy": task.get("plan", {}).get("strategy"),
        "agent_count": len(agents),
        "remote_run_ids": remote_runs,
        "event_count": len(
            task.get("timeline") or task.get("events") or []
        ),
    }


def run_high_risk_case(
    client: Client, unit_id: str, worker_id: str, round_index: int
) -> dict[str, Any]:
    case = {
        "name": "high-risk-approval",
        "mode": "single",
        "goal": (
            "模拟部署到生产的高风险审批链路：本次只允许生成发布计划到"
            " /var/lib/cloud-agents-worker/workspace/e2e/approved-release-plan.md，"
            "禁止连接生产环境、禁止发布、禁止推送代码。审批通过后写入并复读该计划。"
        ),
    }
    conversation, task_id = create_conversation(
        client, case=case, unit_id=unit_id, round_index=round_index
    )
    if conversation.get("status") != "waiting_user":
        raise RuntimeError("high-risk conversation did not wait for approval")
    approvals = client.get("/approvals?status=pending").get("approvals", [])
    approval = next(
        (item for item in approvals if item.get("task_id") == task_id), None
    )
    if approval is None or approval.get("impact", {}).get("level") != "high":
        raise RuntimeError("high-risk approval card is missing")
    decided = client.post(
        f"/approvals/{urllib.parse.quote(str(approval['approval_id']))}/decision",
        {
            "action": "approve",
            "version": approval["version"],
            "confirmed": True,
            "reason": "E2E confirms plan generation only; no production mutation",
        },
    )
    if decided.get("status") != "approved":
        raise RuntimeError(f"approval decision failed: {decided}")
    task = wait_for_task(client, task_id)
    result = assert_remote_result(task, unit_id, worker_id)
    result["approval_id"] = approval["approval_id"]
    result["approval_status"] = decided["status"]
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--token-env", default="RUN_MANAGER_TOKEN")
    parser.add_argument("--unit-id", required=True)
    parser.add_argument("--worker-id", required=True)
    parser.add_argument("--rounds", type=int, default=1)
    parser.add_argument("--round-start", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args()
    token = os.environ.get(args.token_env, "")
    if not token:
        raise SystemExit(f"{args.token_env} is required")
    if args.rounds < 1:
        raise SystemExit("--rounds must be at least 1")
    if args.round_start < 1:
        raise SystemExit("--round-start must be at least 1")
    client = Client(args.base_url, token, args.timeout)
    results: list[dict[str, Any]] = []
    for round_index in range(args.round_start, args.round_start + args.rounds):
        for case in CASES:
            _, task_id = create_conversation(
                client, case=case, unit_id=args.unit_id, round_index=round_index
            )
            task = wait_for_task(client, task_id)
            result = assert_remote_result(task, args.unit_id, args.worker_id)
            result.update({"case": case["name"], "round": round_index})
            results.append(result)
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        approval_result = run_high_risk_case(
            client, args.unit_id, args.worker_id, round_index
        )
        approval_result.update({"case": "high-risk-approval", "round": round_index})
        results.append(approval_result)
        print(json.dumps(approval_result, ensure_ascii=False, sort_keys=True))
    print(
        json.dumps(
            {
                "ok": True,
                "unit_id": args.unit_id,
                "worker_id": args.worker_id,
                "rounds": args.rounds,
                "case_count": len(results),
                "results": results,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
