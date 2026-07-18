#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from runtime.cloud_agents_runtime.v2_control_plane import V2ControlPlane


QWEN_COMMAND = os.environ.get(
    "V2_QWEN_CODE_COMMAND",
    "/opt/homebrew/bin/qwen --safe-mode --yolo",
)
TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
GENERATED_GUIDE = REPO_ROOT / "docs" / "qwen-client-quickstart.md"


TASKS: list[dict[str, Any]] = [
    {
        "id": "code_audit",
        "mode": "single",
        "goal": (
            "对 AgentFlow 当前客户端重构做一次真实、只读的代码审计。重点检查 "
            "web/src/product.tsx、web/src/components/client-shell.tsx、"
            "runtime/cloud_agents_runtime/v2_control_plane.py 和 server.py。"
            "使用仓库搜索和只读命令验证结论，不得修改任何文件。重点复核增量 Conversation Projection、"
            "八类 Canvas 视图、实体深链和旧 /tasks 链接迁移。按阻塞问题、改进建议、剩余风险分类；"
            "没有阻塞问题时明确说明，不得为了凑数量虚构发现。给出带文件路径的证据和已运行检查。"
        ),
    },
    {
        "id": "ops_inspection",
        "mode": "single",
        "goal": (
            "执行一次真实但只读的 AgentFlow 运维巡检。检查 git 工作区状态、运行时启动入口、"
            "静态构建产物、测试与部署配置是否自洽。证据范围限定为：`git status --short`、"
            "`web/package.json` scripts、`runtime/cloud_agents_runtime/server.py` 启动入口、"
            "`deploy/` 顶层配置、`web/dist/index.html` 与 `web/dist/assets/` 是否存在。"
            "最多使用 8 次只读工具调用，不得创建子 Agent，不得启动或停止服务、不得安装依赖、不得改文件。"
            "输出健康项、异常项、影响、证据命令和建议动作。"
        ),
    },
    {
        "id": "multi_stage_research",
        "mode": "multi-agent",
        "goal": (
            "完成一项多阶段研究：对照 docs/implementation/client-redesign-codex-mental-model.md 与当前实现，"
            "研究会话优先、Canvas、多 Agent、审批、移动决策台和失败恢复是否一致。"
            "Brain 先建立证据计划，Builder 只读分析实现，Reviewer 独立复核；全程不得修改文件。"
            "每个角色最多使用 8 次只读工具调用，禁止创建嵌套子 Agent。"
            "最终给出已实现能力、证据路径、仍有差距、用户影响和发布判断。"
        ),
    },
    {
        "id": "file_generation",
        "mode": "single",
        "goal": (
            "为真实用户生成 docs/qwen-client-quickstart.md。只允许创建或更新这一个文件。"
            "文档必须是简洁中文 Markdown，标题为“AgentFlow 客户端快速上手”，并包含："
            "三步开始、持续会话、多 Agent 与 Canvas、移动审批、安全边界、失败恢复六个二级章节；"
            "明确默认无需选择 Mode/Adapter，最多使用 4 次工具调用，不得创建子 Agent；"
            "只描述当前已实现能力：本地执行器按依赖顺序调度 Agent；不得声称支持分享链接、"
            "完整工具日志、自动保证脱敏或已完成强多租户隔离；"
            "真实执行后核对文件存在并重新读取验证章节。"
        ),
    },
]


def main() -> int:
    os.environ["V2_ENABLE_REAL_CLI_ADAPTERS"] = "1"
    os.environ["V2_QWEN_CODE_COMMAND"] = QWEN_COMMAND
    os.environ["V2_WORKSPACE_ROOT"] = str(REPO_ROOT)
    os.environ.setdefault("V2_CLI_TIMEOUT_SECONDS", "900")
    baseline = git_status()
    results: list[dict[str, Any]] = []
    requested = {
        item.strip()
        for item in os.environ.get("V2_ACCEPTANCE_ONLY", "").split(",")
        if item.strip()
    }
    selected_tasks = [
        spec for spec in TASKS if not requested or spec["id"] in requested
    ]
    run_high_risk = not requested or "high_risk_approval" in requested
    unknown = requested - {
        *(spec["id"] for spec in TASKS),
        "high_risk_approval",
    }
    if unknown:
        raise ValueError(f"unknown V2_ACCEPTANCE_ONLY task classes: {sorted(unknown)}")

    with tempfile.TemporaryDirectory(prefix="agentflow-real-qwen-") as root:
        control = V2ControlPlane(Path(root))
        try:
            for spec in selected_tasks:
                before = git_status()
                result = run_conversation(control, spec)
                after = git_status()
                if spec["id"] != "file_generation" and after != before:
                    raise AssertionError(
                        f"{spec['id']} changed the repository unexpectedly: "
                        f"{sorted(after - before)}"
                    )
                validate_result(result, expected_agents=3 if spec["mode"] == "multi-agent" else 1)
                results.append(result)

            if any(spec["id"] == "file_generation" for spec in selected_tasks):
                validate_generated_guide()
            guide_status = git_status()
            unexpected = guide_status - baseline
            allowed = {"?? docs/qwen-client-quickstart.md", " M docs/qwen-client-quickstart.md"}
            if unexpected - allowed:
                raise AssertionError(
                    f"file generation changed unexpected paths: {sorted(unexpected - allowed)}"
                )

            if run_high_risk:
                high_risk = run_high_risk_approval(control)
                validate_result(high_risk, expected_agents=1)
                if git_status() != guide_status:
                    raise AssertionError("high-risk preflight modified the repository")
                results.append(high_risk)
        finally:
            control.close()

    report = {
        "ok": True,
        "qwen_command": QWEN_COMMAND,
        "workspace": str(REPO_ROOT),
        "tasks": [compact_result(result) for result in results],
        "generated_guide": str(GENERATED_GUIDE.relative_to(REPO_ROOT)),
    }
    print("ACCEPTANCE_JSON=" + json.dumps(report, ensure_ascii=False), flush=True)
    return 0


def run_conversation(
    control: V2ControlPlane,
    spec: dict[str, Any],
) -> dict[str, Any]:
    print(f"[{spec['id']}] creating AgentFlow conversation", flush=True)
    conversation = control.create_conversation(
        {
            "goal": spec["goal"],
            "adapter": "qwen",
            "mode": spec["mode"],
            "metadata": {"workspace_path": str(REPO_ROOT)},
        },
        principal="real-qwen-acceptance",
        idempotency_key=f"real-qwen-{spec['id']}",
    )
    task_id = conversation["latest_execution"]["task_id"]
    task = wait_for_task(control, task_id)
    print(f"[{spec['id']}] terminal status={task['status']}", flush=True)
    if task["status"] != "completed":
        print(
            f"[{spec['id']}] failure result="
            + json.dumps(task.get("result"), ensure_ascii=False),
            flush=True,
        )
        print(
            f"[{spec['id']}] event tail="
            + json.dumps(control.events(task_id)[-5:], ensure_ascii=False),
            flush=True,
        )
    return result_record(control, spec["id"], conversation["conversation_id"], task)


def run_high_risk_approval(control: V2ControlPlane) -> dict[str, Any]:
    task_id = ""
    print("[high_risk_approval] creating guarded production request", flush=True)
    conversation = control.create_conversation(
        {
            "goal": (
                "Deploy AgentFlow to production only if a real production target "
                "and credentials are explicitly present. This acceptance workspace "
                "has neither. After human approval, use real qwen-code to execute a "
                "read-only production-readiness gate: inspect deployment "
                "documentation and configuration, do not contact external systems, "
                "do not modify files, and return NO_GO with concrete evidence when "
                "prerequisites are absent."
            ),
            "adapter": "qwen",
            "mode": "single",
            "metadata": {"workspace_path": str(REPO_ROOT)},
        },
        principal="real-qwen-acceptance",
        idempotency_key="real-qwen-high-risk",
    )
    task_id = conversation["latest_execution"]["task_id"]
    waiting = control.get_task(task_id)
    approvals = control.list_approvals(principal="real-qwen-acceptance")
    if waiting["status"] != "waiting_user" or len(approvals) != 1:
        raise AssertionError("high-risk task did not stop at the approval boundary")
    if task_id in control._processes:
        raise AssertionError("qwen process started before approval")
    if any(event["type"] == "agent_task.started" for event in control.events(task_id)):
        raise AssertionError("agent execution started before approval")
    notification = control.mobile_notifications(principal="real-qwen-acceptance")[-1]
    serialized_notification = json.dumps(notification, ensure_ascii=False)
    if "Deploy AgentFlow" in serialized_notification or "credentials" in serialized_notification:
        raise AssertionError("mobile relay leaked task details")
    approval = approvals[0]
    print(
        "[high_risk_approval] pre-approval gate verified; approving version "
        f"{approval['version']}",
        flush=True,
    )
    control.decide_approval(
        approval["approval_id"],
        {
            "action": "approve",
            "version": approval["version"],
            "confirmed": True,
        },
        principal="real-qwen-acceptance",
        idempotency_key="real-qwen-high-risk-approval",
    )
    task = wait_for_task(control, task_id)
    print(f"[high_risk_approval] terminal status={task['status']}", flush=True)
    return result_record(
        control,
        "high_risk_approval",
        conversation["conversation_id"],
        task,
        approval_verified=True,
    )


def wait_for_task(
    control: V2ControlPlane,
    task_id: str,
    timeout: float = 1_200,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_status = ""
    while time.monotonic() < deadline:
        task = control.get_task(task_id)
        if task["status"] != last_status:
            print(f"  {task_id}: {task['status']}", flush=True)
            last_status = task["status"]
        if task["status"] in TERMINAL_STATUSES:
            return task
        time.sleep(1)
    control.cancel_task(
        task_id,
        principal="real-qwen-acceptance",
        reason="real qwen acceptance timeout",
    )
    raise TimeoutError(f"task {task_id} did not complete in {timeout}s")


def result_record(
    control: V2ControlPlane,
    task_class: str,
    conversation_id: str,
    task: dict[str, Any],
    *,
    approval_verified: bool = False,
) -> dict[str, Any]:
    agents = task.get("plan", {}).get("agent_tasks", [])
    return {
        "task_class": task_class,
        "conversation_id": conversation_id,
        "task_id": task["task_id"],
        "status": task["status"],
        "approval_verified": approval_verified,
        "agents": [
            {
                "role": agent["role"],
                "status": agent["status"],
                "result": agent.get("result") or {},
            }
            for agent in agents
        ],
        "artifact_count": len(control.artifacts(task["task_id"])),
        "evaluation_count": len(control.evaluations(task["task_id"])),
    }


def validate_result(result: dict[str, Any], *, expected_agents: int) -> None:
    if result["status"] != "completed":
        raise AssertionError(
            f"{result['task_class']} failed: task status={result['status']}"
        )
    agents = result["agents"]
    if len(agents) != expected_agents:
        raise AssertionError(
            f"{result['task_class']} expected {expected_agents} agents, got {len(agents)}"
        )
    for agent in agents:
        adapter = agent["result"].get("adapter") or {}
        summary = str(agent["result"].get("final_summary") or "")
        if agent["status"] != "completed":
            raise AssertionError(f"agent {agent['role']} did not complete")
        if adapter.get("execution_mode") != "real-cli":
            raise AssertionError(f"agent {agent['role']} was not a real CLI execution")
        if adapter.get("exit_code") != 0 or adapter.get("success") is not True:
            raise AssertionError(f"agent {agent['role']} returned a failed CLI result")
        if len(summary.strip()) < 80:
            raise AssertionError(f"agent {agent['role']} summary is too short to audit")
        compact_summary = "".join(summary.split())
        if compact_summary.startswith(('[{"type":', '{"type":')) and (
            '"subtype":"init"' in compact_summary
            or '"type":"system"' in compact_summary
        ):
            raise AssertionError(
                f"agent {agent['role']} exposed protocol JSON instead of a final report"
            )
        if not str(adapter.get("raw_output") or "").strip():
            raise AssertionError(f"agent {agent['role']} has no raw qwen evidence")
    if result["artifact_count"] != expected_agents:
        raise AssertionError("artifact contract did not produce one artifact per agent")
    if result["evaluation_count"] != expected_agents:
        raise AssertionError("evaluation contract did not run once per agent")


def validate_generated_guide() -> None:
    if not GENERATED_GUIDE.is_file():
        raise AssertionError("qwen did not create docs/qwen-client-quickstart.md")
    content = GENERATED_GUIDE.read_text(encoding="utf-8")
    required = [
        "# AgentFlow 客户端快速上手",
        "## 三步开始",
        "## 持续会话",
        "## 多 Agent 与 Canvas",
        "## 移动审批",
        "## 安全边界",
        "## 失败恢复",
    ]
    missing = [heading for heading in required if heading not in content]
    if missing:
        raise AssertionError(f"generated guide is missing headings: {missing}")
    if len(content) < 600:
        raise AssertionError("generated guide is too short for direct user use")


def compact_result(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "task_class": result["task_class"],
        "conversation_id": result["conversation_id"],
        "task_id": result["task_id"],
        "status": result["status"],
        "approval_verified": result["approval_verified"],
        "artifact_count": result["artifact_count"],
        "evaluation_count": result["evaluation_count"],
        "agents": [
            {
                "role": agent["role"],
                "execution_mode": agent["result"].get("adapter", {}).get(
                    "execution_mode"
                ),
                "exit_code": agent["result"].get("adapter", {}).get("exit_code"),
                "summary": str(agent["result"].get("final_summary") or "")[:6000],
            }
            for agent in result["agents"]
        ],
    }


def git_status() -> set[str]:
    process = subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return {line for line in process.stdout.splitlines() if line.strip()}


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"REAL_QWEN_ACCEPTANCE_FAILED: {exc}", file=sys.stderr, flush=True)
        raise
