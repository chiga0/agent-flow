from __future__ import annotations

import unittest

from runtime.cloud_agents_runtime.events import RuntimeEvent
from runtime.cloud_agents_runtime.ui_projection import project_event, project_events


class UIProjectionTest(unittest.TestCase):
    def test_projects_core_runtime_events_to_daemon_events(self) -> None:
        events = [
            runtime_event("input.accepted", 1, {"prompt_preview": "hello"}),
            runtime_event("message.delta", 2, {"text": "world"}),
            runtime_event("reasoning.delta", 3, {"text": "thinking"}),
            runtime_event("tool.started", 4, {"tool": "shell", "command": "pwd"}),
            runtime_event("tool.updated", 5, {"tool": "shell", "stdout": "/tmp"}),
            runtime_event("tool.completed", 6, {"tool": "shell", "stdout": "done"}),
            runtime_event("shell.output", 7, {"stdout": "line"}),
            runtime_event("permission.requested", 8, {"permission_id": "perm-1"}),
            runtime_event("permission.resolved", 9, {"permission_id": "perm-1"}),
            runtime_event("run.completed", 10, {}),
            runtime_event("run.failed", 11, {"reason": "boom"}),
            runtime_event("run.cancelled", 12, {"reason": "stop"}),
            runtime_event("stream.warning", 13, {"reason": "slow"}),
        ]

        projected = project_events(events, source_adapter="fake")

        self.assertEqual([event["id"] for event in projected], list(range(1, 14)))
        self.assertTrue(all(event["v"] == 1 for event in projected))
        self.assertEqual(projected[0]["type"], "session_update")
        self.assertEqual(
            projected[0]["data"]["update"]["sessionUpdate"],
            "user_message_chunk",
        )
        self.assertEqual(
            projected[1]["data"]["update"]["sessionUpdate"],
            "agent_message_chunk",
        )
        self.assertEqual(
            projected[2]["data"]["update"]["sessionUpdate"],
            "agent_thought_chunk",
        )
        self.assertEqual(projected[3]["data"]["update"]["sessionUpdate"], "tool_call")
        self.assertEqual(
            projected[5]["data"]["update"]["toolCall"]["status"],
            "completed",
        )
        self.assertEqual(projected[6]["type"], "shell_output")
        self.assertEqual(projected[7]["type"], "permission_request")
        self.assertEqual(projected[8]["type"], "permission_resolved")
        self.assertEqual(projected[9]["type"], "turn_complete")
        self.assertEqual(projected[10]["type"], "turn_error")
        self.assertEqual(projected[11]["type"], "prompt_cancelled")
        self.assertEqual(projected[12]["type"], "stream_error")
        self.assertEqual(projected[0]["_meta"]["runtimeSequence"], 1)
        self.assertEqual(projected[0]["_meta"]["sourceAdapter"], "fake")

    def test_malformed_runtime_event_becomes_redacted_status(self) -> None:
        projected = project_event(
            runtime_event(
                "custom.debug",
                1,
                {
                    "authorization": "Bearer secret",
                    "nested": {"api_token": "abc", "safe": "ok"},
                },
            )
        )

        self.assertEqual(projected["type"], "session_update")
        status = projected["data"]["update"]["status"]
        self.assertEqual(status["eventType"], "custom.debug")
        self.assertEqual(status["data"]["authorization"], "[redacted]")
        self.assertEqual(status["data"]["nested"]["api_token"], "[redacted]")
        self.assertEqual(status["data"]["nested"]["safe"], "ok")

    def test_qwen_daemon_raw_event_can_passthrough_with_runtime_meta(self) -> None:
        projected = project_event(
            runtime_event(
                "adapter.event",
                7,
                {
                    "adapter": "qwen",
                    "raw": {
                        "id": "native-id",
                        "v": 1,
                        "type": "session_update",
                        "data": {
                            "update": {
                                "sessionUpdate": "agent_message_chunk",
                                "content": {"type": "text", "text": "hi"},
                            }
                        },
                    },
                },
            )
        )

        self.assertEqual(projected["id"], 7)
        self.assertEqual(projected["type"], "session_update")
        self.assertEqual(projected["_meta"]["runtimeSequence"], 7)
        self.assertEqual(projected["_meta"]["sourceAdapter"], "qwen")

    def test_projection_defensive_edges(self) -> None:
        invalid_raw = project_event(runtime_event("adapter.event", 1, {"raw": "bad"}))
        self.assertEqual(invalid_raw["data"]["update"]["sessionUpdate"], "status")

        invalid_type = project_event(runtime_event("adapter.event", 2, {"raw": {"data": {}}}))
        self.assertEqual(invalid_type["data"]["update"]["sessionUpdate"], "status")

        invalid_data = project_event(
            runtime_event("adapter.event", 3, {"raw": {"type": "session_update", "data": []}})
        )
        self.assertEqual(invalid_data["data"]["update"]["sessionUpdate"], "status")

        raw_text = project_event(
            runtime_event(
                "message.delta",
                4,
                {"raw": {"data": {"message": "from raw fallback"}}},
            )
        )
        self.assertEqual(
            raw_text["data"]["update"]["content"]["text"],
            "from raw fallback",
        )

        fallback_permission = project_event(runtime_event("permission.requested", 5, {}))
        self.assertEqual(fallback_permission["data"]["requestId"], "permission")

        long_debug = project_event(
            runtime_event("custom.debug", 6, {"safe": "x" * 2100})
        )
        self.assertEqual(len(long_debug["data"]["update"]["status"]["data"]["safe"]), 2003)

        bad_timestamp = RuntimeEvent(
            type="run.completed",
            run_id="run_projection",
            sequence=7,
            data={},
            id="evt_7",
            created_at="not-a-date",
        )
        self.assertEqual(project_event(bad_timestamp)["_meta"]["serverTimestamp"], 0)


def runtime_event(event_type: str, sequence: int, data: dict[str, object]) -> RuntimeEvent:
    return RuntimeEvent(
        type=event_type,
        run_id="run_projection",
        sequence=sequence,
        data=data,
        id=f"evt_{sequence}",
        created_at="2026-07-04T00:00:00.000+00:00",
    )


if __name__ == "__main__":
    unittest.main()
