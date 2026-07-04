from __future__ import annotations

from datetime import datetime
from typing import Any

from .events import RuntimeEvent

DaemonEvent = dict[str, Any]

SENSITIVE_KEY_PARTS = (
    "authorization",
    "cookie",
    "password",
    "secret",
    "token",
    "private_key",
    "api_key",
)


def project_events(
    events: list[RuntimeEvent],
    *,
    source_adapter: str | None = None,
) -> list[DaemonEvent]:
    return [project_event(event, source_adapter=source_adapter) for event in events]


def project_event(
    event: RuntimeEvent,
    *,
    source_adapter: str | None = None,
) -> DaemonEvent:
    passthrough = qwen_passthrough_event(event)
    if passthrough is not None:
        return with_projection_envelope(passthrough, event, source_adapter=source_adapter)

    data = event.data or {}
    if event.type == "input.accepted":
        return session_update(
            event,
            "user_message_chunk",
            {
                "content": {
                    "type": "text",
                    "text": text_from(data, "prompt", "prompt_preview"),
                }
            },
            source_adapter=source_adapter,
        )
    if event.type == "message.delta":
        return session_update(
            event,
            "agent_message_chunk",
            {
                "content": {
                    "type": "text",
                    "text": text_from(data, "text", "delta", "message"),
                }
            },
            source_adapter=source_adapter,
        )
    if event.type == "reasoning.delta":
        return session_update(
            event,
            "agent_thought_chunk",
            {
                "content": {
                    "type": "text",
                    "text": text_from(data, "text", "delta", "message"),
                }
            },
            source_adapter=source_adapter,
        )
    if event.type == "tool.started":
        return session_update(
            event,
            "tool_call",
            {"toolCall": tool_payload(data, status="running")},
            source_adapter=source_adapter,
        )
    if event.type == "tool.updated":
        return session_update(
            event,
            "tool_call_update",
            {"toolCall": tool_payload(data, status=string_value(data.get("status")) or "running")},
            source_adapter=source_adapter,
        )
    if event.type == "tool.completed":
        return session_update(
            event,
            "tool_call_update",
            {"toolCall": tool_payload(data, status="completed")},
            source_adapter=source_adapter,
        )
    if event.type == "shell.output":
        return daemon_event(
            event,
            "shell_output",
            {
                "stdout": string_value(data.get("stdout")),
                "stderr": string_value(data.get("stderr")),
                "stream": string_value(data.get("stream")) or "stdout",
                "toolCallId": string_value(data.get("tool_call_id") or data.get("toolCallId")),
            },
            source_adapter=source_adapter,
        )
    if event.type == "permission.requested":
        return daemon_event(
            event,
            "permission_request",
            {
                "requestId": permission_id(data),
                "prompt": text_from(data, "prompt", "message"),
                "tool": string_value(data.get("tool")),
                "options": data.get("options") if isinstance(data.get("options"), list) else [],
                "context": sanitize_for_ui(data),
            },
            source_adapter=source_adapter,
        )
    if event.type == "permission.resolved":
        return daemon_event(
            event,
            "permission_resolved",
            {
                "requestId": permission_id(data),
                "decision": string_value(data.get("decision") or data.get("outcome")),
                "optionId": string_value(data.get("option_id")),
                "actor": string_value(data.get("actor") or data.get("decided_by")),
            },
            source_adapter=source_adapter,
        )
    if event.type == "run.completed":
        return daemon_event(
            event,
            "turn_complete",
            {"status": "completed", "result": sanitize_for_ui(data)},
            source_adapter=source_adapter,
        )
    if event.type == "run.failed":
        return daemon_event(
            event,
            "turn_error",
            {"message": text_from(data, "reason", "error") or "run failed"},
            source_adapter=source_adapter,
        )
    if event.type == "run.cancelled":
        return daemon_event(
            event,
            "prompt_cancelled",
            {"reason": text_from(data, "reason", "message") or "cancelled"},
            source_adapter=source_adapter,
        )
    if event.type == "stream.warning":
        return daemon_event(
            event,
            "stream_error",
            {"message": text_from(data, "reason", "message") or "stream warning"},
            source_adapter=source_adapter,
        )
    if event.type == "event.gap_detected":
        return daemon_event(
            event,
            "stream_error",
            {
                "message": "event gap detected; replay from canonical event store",
                "requestedLastEventId": data.get("requested_last_sequence"),
                "availableLastEventId": data.get("available_last_sequence"),
            },
            source_adapter=source_adapter,
        )

    return session_update(
        event,
        "status",
        {
            "status": {
                "message": event.type,
                "eventType": event.type,
                "data": sanitize_for_ui(data),
            }
        },
        source_adapter=source_adapter,
    )


def qwen_passthrough_event(event: RuntimeEvent) -> DaemonEvent | None:
    if event.type != "adapter.event":
        return None
    raw = event.data.get("raw") if isinstance(event.data, dict) else None
    if not isinstance(raw, dict):
        return None
    raw_type = raw.get("type")
    raw_data = raw.get("data")
    if not isinstance(raw_type, str) or not raw_type:
        return None
    if raw_data is not None and not isinstance(raw_data, dict):
        return None
    return dict(raw)


def with_projection_envelope(
    payload: DaemonEvent,
    event: RuntimeEvent,
    *,
    source_adapter: str | None = None,
) -> DaemonEvent:
    projected = dict(payload)
    projected["id"] = event.sequence
    projected["v"] = 1
    meta = dict(projected.get("_meta") or {})
    meta.update(meta_for(event, source_adapter=source_adapter))
    projected["_meta"] = meta
    return projected


def session_update(
    event: RuntimeEvent,
    session_update_type: str,
    update: dict[str, Any],
    *,
    source_adapter: str | None = None,
) -> DaemonEvent:
    return daemon_event(
        event,
        "session_update",
        {"update": {"sessionUpdate": session_update_type, **update}},
        source_adapter=source_adapter,
    )


def daemon_event(
    event: RuntimeEvent,
    event_type: str,
    data: dict[str, Any],
    *,
    source_adapter: str | None = None,
) -> DaemonEvent:
    return {
        "id": event.sequence,
        "v": 1,
        "type": event_type,
        "data": data,
        "_meta": meta_for(event, source_adapter=source_adapter),
    }


def meta_for(event: RuntimeEvent, *, source_adapter: str | None = None) -> dict[str, Any]:
    adapter = source_adapter or string_value(event.data.get("adapter"))
    return {
        "serverTimestamp": timestamp_ms(event.created_at),
        "runtimeRunId": event.run_id,
        "runtimeEventId": event.id,
        "runtimeSequence": event.sequence,
        "runtimeEventType": event.type,
        "sourceAdapter": adapter,
    }


def tool_payload(data: dict[str, Any], *, status: str) -> dict[str, Any]:
    return {
        "id": string_value(data.get("tool_call_id") or data.get("toolCallId") or data.get("id")),
        "name": string_value(data.get("name") or data.get("tool")),
        "status": status,
        "input": sanitize_for_ui(data.get("input") or data.get("args") or data.get("command")),
        "output": sanitize_for_ui(data.get("output") or data.get("stdout") or data.get("stderr")),
    }


def sanitize_for_ui(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if is_sensitive_key(key_text):
                sanitized[key_text] = "[redacted]"
            else:
                sanitized[key_text] = sanitize_for_ui(item)
        return sanitized
    if isinstance(value, list):
        return [sanitize_for_ui(item) for item in value]
    if isinstance(value, str):
        return value if len(value) <= 2000 else f"{value[:2000]}..."
    return value


def is_sensitive_key(key: str) -> bool:
    lowered = key.lower().replace("-", "_")
    return any(part in lowered for part in SENSITIVE_KEY_PARTS)


def permission_id(data: dict[str, Any]) -> str:
    return (
        string_value(data.get("permission_id"))
        or string_value(data.get("requestId"))
        or string_value(data.get("id"))
        or "permission"
    )


def text_from(data: dict[str, Any], *keys: str) -> str:
    for key in keys:
        text = string_value(data.get(key))
        if text:
            return text
    raw = data.get("raw")
    if isinstance(raw, dict):
        raw_data = raw.get("data")
        if isinstance(raw_data, dict):
            for key in keys:
                text = string_value(raw_data.get(key))
                if text:
                    return text
    return ""


def string_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def timestamp_ms(value: str) -> int:
    try:
        normalized = value.replace("Z", "+00:00")
        return int(datetime.fromisoformat(normalized).timestamp() * 1000)
    except ValueError:
        return 0
