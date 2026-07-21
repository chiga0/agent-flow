from __future__ import annotations

import hashlib
import json
from typing import Any


EVENT_CONTRACT_VERSION = "2026-07-22"
MAX_EVENT_TEXT = 64_000
MAX_EVENT_BYTES = 256_000
DAEMON_PASSTHROUGH_TYPES = {
    "session_update",
    "shell_output",
    "tool_output",
    "model_switched",
    "model_switch_failed",
}
DAEMON_SESSION_UPDATE_TYPES = {
    "agent_message_chunk",
    "agent_thought_chunk",
    "tool_call",
    "tool_call_update",
    "shell_output",
    "tool_output",
    "plan",
    "plan_update",
}
WORKER_EVENT_TYPES = {
    "agent.message",
    "agent.thought",
    "agent.status",
    "tool.started",
    "tool.updated",
    "tool.completed",
    "tool.failed",
    "shell.output",
    "permission.requested",
    "permission.applied",
    "adapter.daemon_event",
    "adapter.observed",
    "workspace.prepared",
}


def validate_worker_event(event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Validate and bound one worker-authored canonical event."""
    if event_type not in WORKER_EVENT_TYPES:
        raise ValueError(f"unsupported worker event type: {event_type}")
    if not isinstance(payload, dict):
        raise ValueError("event payload must be an object")
    data = _bounded(payload)
    if event_type in {"agent.message", "agent.thought"}:
        _require_text(data, "message")
    elif event_type == "agent.status":
        _require_text(data, "status")
    elif event_type.startswith("tool."):
        _require_text(data, "tool_call_id")
        _require_text(data, "name")
    elif event_type == "shell.output":
        _require_text(data, "output")
    elif event_type in {"permission.requested", "permission.applied"}:
        _require_text(data, "permission_id")
        if event_type == "permission.applied" and not isinstance(data.get("decision"), dict):
            raise ValueError("permission.applied requires a decision object")
    elif event_type == "adapter.daemon_event":
        daemon_event = data.get("event")
        if not isinstance(daemon_event, dict):
            raise ValueError("adapter.daemon_event requires an event object")
        if not isinstance(daemon_event.get("type"), str) or not isinstance(
            daemon_event.get("data"), dict
        ):
            raise ValueError("daemon event requires string type and object data")
        if daemon_event["type"] not in DAEMON_PASSTHROUGH_TYPES:
            raise ValueError("daemon event type is not safe for worker passthrough")
        if daemon_event["type"] == "session_update":
            update = daemon_event["data"].get("update")
            update_type = update.get("sessionUpdate") if isinstance(update, dict) else None
            if update_type not in DAEMON_SESSION_UPDATE_TYPES:
                raise ValueError("daemon session update is not safe for worker passthrough")
    data["contract_version"] = EVENT_CONTRACT_VERSION
    if len(json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")) > MAX_EVENT_BYTES:
        raise ValueError("event payload exceeds maximum encoded size")
    return data


def translate_adapter_record(adapter: str, record: str) -> list[dict[str, Any]]:
    """Translate one complete CLI output record into canonical UI events."""
    raw = record.strip()
    if not raw:
        return []
    source_event_id = hashlib.sha256(
        f"{adapter}\0{raw}".encode("utf-8", errors="replace")
    ).hexdigest()
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return [_event("agent.message", {"message": raw}, adapter, source_event_id, raw)]
    if not isinstance(value, dict):
        return [_event("agent.message", {"message": raw}, adapter, source_event_id, value)]

    if _is_daemon_event(value):
        return [
            _event(
                "adapter.daemon_event",
                {"event": value},
                adapter,
                source_event_id,
                value,
            )
        ]
    translator = {
        "qwen": _translate_qwen,
        "claude": _translate_qwen,
        "codex": _translate_codex,
        "opencode": _translate_opencode,
    }.get(adapter)
    translated = translator(value) if translator else []
    if not translated:
        translated = [("adapter.observed", {})]
    return [
        _event(kind, payload, adapter, f"{source_event_id}:{index}", value)
        for index, (kind, payload) in enumerate(translated)
    ]


def _translate_qwen(value: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    result: list[tuple[str, dict[str, Any]]] = []
    event_type = str(value.get("type") or "")
    if event_type == "stream_event":
        stream = value.get("event") if isinstance(value.get("event"), dict) else {}
        delta = stream.get("delta") if isinstance(stream.get("delta"), dict) else {}
        delta_type = str(delta.get("type") or "")
        text = _first_text(delta, "text", "thinking")
        if text:
            kind = "agent.thought" if "thinking" in delta_type else "agent.message"
            result.append((kind, {"message": text, "partial": True}))
        return result
    message = value.get("message") if isinstance(value.get("message"), dict) else {}
    content = message.get("content")
    if isinstance(content, str) and content:
        result.append(("agent.message", {"message": content}))
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = str(block.get("type") or "")
            if block_type == "text" and block.get("text"):
                result.append(("agent.message", {"message": str(block["text"])}))
            elif block_type in {"thinking", "reasoning"} and (
                block.get("thinking") or block.get("text")
            ):
                result.append(
                    (
                        "agent.thought",
                        {"message": str(block.get("thinking") or block.get("text"))},
                    )
                )
            elif block_type == "tool_use":
                result.append(
                    (
                        "tool.started",
                        _tool_payload(
                            block.get("id"),
                            block.get("name"),
                            block.get("input"),
                            parent_tool_call_id=block.get("parentToolCallId"),
                            subagent_type=block.get("subagentType"),
                        ),
                    )
                )
            elif block_type == "tool_result":
                result.append(
                    (
                        "tool.completed" if not block.get("is_error") else "tool.failed",
                        _tool_payload(
                            block.get("tool_use_id"),
                            block.get("name") or "tool",
                            output=block.get("content"),
                        ),
                    )
                )
    if event_type == "result":
        text = _first_text(value, "result", "message")
        result.append(
            (
                "agent.status",
                {"status": text or "completed", "usage": value.get("usage")},
            )
        )
    elif event_type == "system":
        result.append(("agent.status", {"status": str(value.get("subtype") or "initialized")}))
    return result


def _translate_codex(value: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    event_type = str(value.get("type") or "")
    item = value.get("item") if isinstance(value.get("item"), dict) else value
    item_type = str(item.get("type") or "")
    text = _first_text(item, "text", "message", "output", "content")
    if item_type in {"agent_message", "message"} and text:
        return [("agent.message", {"message": text})]
    if item_type in {"reasoning", "analysis"} and text:
        return [("agent.thought", {"message": text})]
    if item_type in {
        "command_execution",
        "mcp_tool_call",
        "file_change",
        "web_search",
        "todo_list",
        "tool_call",
    }:
        status = str(item.get("status") or "")
        suffix = event_type.rsplit(".", 1)[-1]
        kind = "tool.started" if suffix == "started" else "tool.updated"
        if suffix == "completed" or status in {"completed", "success"}:
            kind = "tool.completed"
        if status in {"failed", "error"}:
            kind = "tool.failed"
        name = _first_text(item, "name", "tool", "command") or item_type
        return [
            (
                kind,
                _tool_payload(
                    item.get("id") or item.get("call_id"),
                    name,
                    item.get("arguments") or item.get("input") or item.get("command"),
                    item.get("aggregated_output") or item.get("output"),
                    kind=item_type,
                    parent_tool_call_id=item.get("parent_tool_call_id"),
                    subagent_type=item.get("subagent_type"),
                ),
            )
        ]
    if event_type.startswith("turn."):
        return [("agent.status", {"status": event_type, "usage": value.get("usage")})]
    if event_type == "error":
        return [("agent.status", {"status": _first_text(value, "message", "error") or "error"})]
    return []


def _translate_opencode(value: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    event_type = str(value.get("type") or "")
    part = value.get("part") if isinstance(value.get("part"), dict) else {}
    if event_type == "text" and part.get("text"):
        return [("agent.message", {"message": str(part["text"])})]
    if event_type == "reasoning" and part.get("text"):
        return [("agent.thought", {"message": str(part["text"])})]
    if event_type == "tool_use":
        state = part.get("state") if isinstance(part.get("state"), dict) else {}
        status = str(state.get("status") or "")
        kind = {
            "completed": "tool.completed",
            "error": "tool.failed",
            "running": "tool.updated",
        }.get(status, "tool.started")
        return [
            (
                kind,
                _tool_payload(
                    part.get("id"),
                    part.get("tool") or "tool",
                    state.get("input"),
                    state.get("output") or state.get("error"),
                    parent_tool_call_id=part.get("parentToolCallId"),
                    subagent_type=part.get("subagentType"),
                ),
            )
        ]
    if event_type in {"step_start", "step_finish"}:
        return [("agent.status", {"status": event_type, "step": part})]
    if event_type == "error":
        return [("agent.status", {"status": _first_text(value, "message", "error") or "error"})]
    return []


def _event(
    event_type: str,
    payload: dict[str, Any],
    adapter: str,
    source_event_id: str,
    native: Any,
) -> dict[str, Any]:
    data = {**payload, "adapter": adapter, "native_event": _compact_native(native)}
    return {
        "type": event_type,
        "payload": validate_worker_event(event_type, data),
        "source_event_id": source_event_id,
    }


def _tool_payload(
    tool_id: Any,
    name: Any,
    input_value: Any = None,
    output: Any = None,
    *,
    kind: str | None = None,
    parent_tool_call_id: Any = None,
    subagent_type: Any = None,
) -> dict[str, Any]:
    tool_name = str(name or "tool")
    resolved_kind = {
        "mcp_tool_call": "mcp",
        "command_execution": "shell",
        "file_change": "file",
    }.get(str(kind), kind) or _tool_kind(tool_name)
    payload = {
        "tool_call_id": str(tool_id or hashlib.sha256(tool_name.encode()).hexdigest()[:16]),
        "name": tool_name,
        "title": tool_name,
        "input": input_value,
        "output": output,
        "kind": resolved_kind,
    }
    if parent_tool_call_id:
        payload["parent_tool_call_id"] = str(parent_tool_call_id)
    if subagent_type:
        payload["subagent_type"] = str(subagent_type)
    return payload


def _tool_kind(name: str) -> str:
    lowered = name.lower()
    if lowered.startswith("mcp__"):
        return "mcp"
    if lowered in {"skill", "skills", "run_skill"} or "skill" in lowered:
        return "skill"
    if lowered in {"task", "spawn_agent", "delegate"} or "subagent" in lowered:
        return "subagent"
    if lowered in {"shell", "bash", "command", "command_execution"}:
        return "shell"
    return "tool"


def _is_daemon_event(value: dict[str, Any]) -> bool:
    return isinstance(value.get("type"), str) and isinstance(value.get("data"), dict) and (
        "v" in value or value["type"] in {"session_update", "turn_complete", "turn_error"}
    )


def _first_text(value: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        item = value.get(key)
        if isinstance(item, str) and item:
            return item
        if isinstance(item, list):
            text = "".join(
                str(part.get("text") or "") for part in item if isinstance(part, dict)
            )
            if text:
                return text
    return None


def _require_text(payload: dict[str, Any], key: str) -> None:
    if not isinstance(payload.get(key), str) or not payload[key]:
        raise ValueError(f"event payload requires non-empty {key}")


def _compact_native(value: Any) -> Any:
    encoded = json.dumps(value, ensure_ascii=False, default=str)
    if len(encoded.encode("utf-8")) <= 128_000:
        return value
    return {
        "truncated": True,
        "sha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
        "preview": encoded[:32_000],
    }


def _bounded(value: Any, depth: int = 0) -> Any:
    if depth >= 12:
        return "[max-depth]"
    if isinstance(value, str):
        return value[:MAX_EVENT_TEXT]
    if isinstance(value, list):
        return [_bounded(item, depth + 1) for item in value[:100]]
    if isinstance(value, dict):
        return {
            str(key)[:200]: _bounded(item, depth + 1)
            for key, item in list(value.items())[:100]
        }
    return value
