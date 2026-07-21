from __future__ import annotations

from typing import Any


def workspace_cwd(task: dict[str, Any]) -> str:
    metadata = task.get("metadata")
    workspace = metadata.get("workspace") if isinstance(metadata, dict) else None
    if isinstance(workspace, dict):
        source_path = workspace.get("source_path")
        if isinstance(source_path, str) and source_path.strip():
            return source_path.strip()
    return f"/aflow/tasks/{task['task_id']}"


def task_agents(task: dict[str, Any]) -> list[dict[str, Any]]:
    plan = task.get("plan")
    agents = plan.get("agent_tasks") if isinstance(plan, dict) else None
    if isinstance(agents, list) and agents:
        return [agent for agent in agents if isinstance(agent, dict)]
    return [
        {
            "agent_task_id": task["task_id"],
            "role": "agent",
            "title": task.get("title") or "Agent",
            "status": task.get("status") or "queued",
            "adapter": task.get("adapter") or "auto",
            "updated_at": task.get("updated_at"),
        }
    ]


def find_agent(task: dict[str, Any], session_id: str) -> dict[str, Any]:
    for agent in task_agents(task):
        if agent.get("agent_task_id") == session_id:
            return agent
    raise KeyError(session_id)


def capabilities(task: dict[str, Any]) -> dict[str, Any]:
    cwd = workspace_cwd(task)
    adapters = sorted(
        {
            str(agent.get("adapter") or task.get("adapter") or "agent")
            for agent in task_agents(task)
        }
    )
    return {
        "v": 1,
        "mode": "http-bridge",
        "features": [
            "session_events",
            "permission_vote",
            "session_permission_vote",
            "session_source_metadata",
        ],
        "modelServices": adapters,
        "transports": ["rest-sse"],
        "workspaceCwd": cwd,
        "qwenCodeVersion": "aflow-gateway",
        "workspaces": [
            {
                "id": task["task_id"],
                "cwd": cwd,
                "displayName": task.get("title") or "Aflow task",
                "primary": True,
                "trusted": True,
                "removable": False,
            }
        ],
    }


def session_summaries(task: dict[str, Any]) -> list[dict[str, Any]]:
    cwd = workspace_cwd(task)
    created_at = task.get("created_at")
    return [
        {
            "sessionId": str(agent["agent_task_id"]),
            "workspaceCwd": cwd,
            "createdAt": created_at,
            "updatedAt": agent.get("updated_at") or task.get("updated_at"),
            "displayName": agent.get("title") or agent.get("role") or "Agent",
            "sourceType": "aflow-agent",
            "sourceId": str(agent["agent_task_id"]),
            "clientCount": 0,
            "hasActivePrompt": agent.get("status") in {"queued", "running"},
            "isWaitingForPermission": agent.get("status") == "waiting_approval",
            "pendingInteractionCount": (
                1 if agent.get("status") == "waiting_approval" else 0
            ),
            "hasTurnError": agent.get("status") == "failed",
        }
        for agent in task_agents(task)
    ]


def session_events(
    task: dict[str, Any],
    events: list[dict[str, Any]],
    session_id: str,
) -> list[dict[str, Any]]:
    find_agent(task, session_id)
    return [
        event
        for event in events
        if not event.get("_meta", {}).get("agentTaskId")
        or event.get("_meta", {}).get("agentTaskId") == session_id
    ]


def restored_session(
    task: dict[str, Any],
    events: list[dict[str, Any]],
    session_id: str,
    *,
    client_id: str | None = None,
) -> dict[str, Any]:
    agent = find_agent(task, session_id)
    replay = session_events(task, events, session_id)
    adapter = str(agent.get("adapter") or task.get("adapter") or "agent")
    return {
        "sessionId": session_id,
        "workspaceCwd": workspace_cwd(task),
        "attached": True,
        "clientId": client_id or f"aflow-{session_id}",
        "createdAt": task.get("created_at"),
        "hasActivePrompt": agent.get("status") in {"queued", "running"},
        "sourceType": "aflow-agent",
        "sourceId": session_id,
        "state": {
            "displayName": agent.get("title") or agent.get("role") or "Agent",
            "models": {
                "currentModelId": adapter,
                "availableModels": [
                    {
                        "modelId": adapter,
                        "baseModelId": adapter,
                        "name": adapter,
                    }
                ],
            },
            "modes": {
                "currentModeId": "default",
                "availableModes": [
                    {
                        "id": "default",
                        "name": "Aflow managed",
                        "description": "Permissions follow the Aflow task policy.",
                    }
                ],
            },
            "_meta": {
                "aflowTaskId": task["task_id"],
                "aflowAgentTaskId": session_id,
                "role": agent.get("role"),
                "status": agent.get("status"),
            },
        },
        "compactedReplay": replay,
        "liveJournal": [],
        "historyHasMore": False,
        "lastEventId": max(
            (int(event.get("id") or 0) for event in replay),
            default=0,
        ),
    }


def session_context(task: dict[str, Any], session_id: str) -> dict[str, Any]:
    agent = find_agent(task, session_id)
    return {
        "v": 1,
        "sessionId": session_id,
        "workspaceCwd": workspace_cwd(task),
        "state": {
            "displayName": agent.get("title") or agent.get("role") or "Agent",
            "_meta": {
                "aflowTaskId": task["task_id"],
                "role": agent.get("role"),
                "status": agent.get("status"),
            },
        },
    }


def extract_prompt(payload: dict[str, Any]) -> str:
    prompt = payload.get("prompt")
    if not isinstance(prompt, list):
        raise ValueError("prompt must contain at least one text block")
    text = "\n".join(
        str(block.get("text") or "")
        for block in prompt
        if isinstance(block, dict) and block.get("type") == "text"
    ).strip()
    if not text:
        raise ValueError("prompt must contain at least one text block")
    return text
