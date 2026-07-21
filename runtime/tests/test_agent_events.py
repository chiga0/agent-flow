from __future__ import annotations

import json
import unittest

from runtime.cloud_agents_runtime.agent_events import (
    EVENT_CONTRACT_VERSION,
    translate_adapter_record,
    validate_worker_event,
)
from runtime.cloud_agents_runtime.v2_control_plane import v2_event_to_daemon_event


class AgentEventContractTest(unittest.TestCase):
    def test_qwen_message_thought_tool_and_native_daemon_events(self) -> None:
        record = json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "thinking", "thinking": "inspect repository"},
                        {"type": "text", "text": "I found the cause."},
                        {
                            "type": "tool_use",
                            "id": "tool-1",
                            "name": "mcp__github__get_issue",
                            "input": {"number": 42},
                        },
                        {
                            "type": "tool_use",
                            "id": "skill-1",
                            "name": "Skill",
                            "input": {"skill": "release-audit"},
                        },
                    ]
                },
            }
        )
        events = translate_adapter_record("qwen", record)
        self.assertEqual(
            [event["type"] for event in events],
            ["agent.thought", "agent.message", "tool.started", "tool.started"],
        )
        self.assertEqual(events[2]["payload"]["tool_call_id"], "tool-1")
        self.assertEqual(events[3]["payload"]["kind"], "skill")
        self.assertEqual(events[0]["payload"]["contract_version"], EVENT_CONTRACT_VERSION)

        daemon = translate_adapter_record(
            "qwen",
            json.dumps(
                {
                    "v": 1,
                    "type": "session_update",
                    "data": {
                        "update": {
                            "sessionUpdate": "agent_message_chunk",
                            "content": {"type": "text", "text": "native"},
                        }
                    },
                }
            ),
        )
        self.assertEqual(daemon[0]["type"], "adapter.daemon_event")

    def test_codex_and_opencode_structured_records(self) -> None:
        codex = translate_adapter_record(
            "codex",
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "id": "cmd-1",
                        "type": "command_execution",
                        "command": "npm test",
                        "status": "completed",
                        "aggregated_output": "12 passed",
                    },
                }
            ),
        )
        self.assertEqual(codex[0]["type"], "tool.completed")
        self.assertEqual(codex[0]["payload"]["output"], "12 passed")

        opencode = translate_adapter_record(
            "opencode",
            json.dumps(
                {
                    "type": "tool_use",
                    "part": {
                        "id": "mcp-1",
                        "tool": "mcp__docs__search",
                        "state": {
                            "status": "running",
                            "input": {"query": "events"},
                        },
                    },
                }
            ),
        )
        self.assertEqual(opencode[0]["type"], "tool.updated")
        self.assertEqual(opencode[0]["payload"]["kind"], "mcp")

    def test_plain_output_and_contract_rejection(self) -> None:
        event = translate_adapter_record("codex", "plain CLI output")[0]
        self.assertEqual(event["type"], "agent.message")
        self.assertEqual(event["payload"]["message"], "plain CLI output")
        with self.assertRaisesRegex(ValueError, "unsupported worker event"):
            validate_worker_event("task.completed", {"summary": "forged"})
        with self.assertRaisesRegex(ValueError, "non-empty message"):
            validate_worker_event("agent.message", {"message": ""})
        applied = validate_worker_event(
            "permission.applied",
            {"permission_id": "perm-1", "decision": {"allow": True}},
        )
        self.assertEqual(applied["decision"], {"allow": True})
        with self.assertRaisesRegex(ValueError, "decision object"):
            validate_worker_event(
                "permission.applied", {"permission_id": "perm-1", "decision": "yes"}
            )
        whitespace_delta = translate_adapter_record(
            "qwen",
            json.dumps(
                {
                    "type": "stream_event",
                    "event": {
                        "type": "content_block_delta",
                        "delta": {"type": "text_delta", "text": " "},
                    },
                }
            ),
        )
        self.assertEqual(whitespace_delta[0]["payload"]["message"], " ")
        with self.assertRaisesRegex(ValueError, "not safe"):
            validate_worker_event(
                "adapter.daemon_event",
                {"event": {"type": "turn_complete", "data": {}}},
            )

    def test_daemon_projection_uses_webshell_conformance_shape(self) -> None:
        base = {
            "task_id": "task-1",
            "sequence": 7,
            "actor": "builder",
            "created_at": "2026-07-22T00:00:00Z",
        }
        thought = v2_event_to_daemon_event(
            {
                **base,
                "type": "agent.thought",
                "payload": {"agent_task_id": "agent-1", "message": "reasoning summary"},
            }
        )
        self.assertEqual(
            thought["data"]["update"]["sessionUpdate"], "agent_thought_chunk"
        )
        tool = v2_event_to_daemon_event(
            {
                **base,
                "type": "tool.started",
                "payload": {
                    "agent_task_id": "agent-1",
                    "tool_call_id": "tool-1",
                    "name": "mcp__github__get_issue",
                    "input": {"number": 42},
                },
            }
        )
        update = tool["data"]["update"]
        self.assertEqual(update["sessionUpdate"], "tool_call")
        self.assertEqual(update["toolCallId"], "tool-1")
        self.assertEqual(update["rawInput"], {"number": 42})


if __name__ == "__main__":
    unittest.main()
