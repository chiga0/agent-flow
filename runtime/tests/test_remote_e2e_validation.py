from __future__ import annotations

import unittest

from scripts.validate_remote_execution_units import assert_remote_result


def remote_task(message: str) -> dict[str, object]:
    return {
        "task_id": "task_test",
        "status": "completed",
        "metadata": {"dispatch": {"execution_unit_id": "ecs-test"}},
        "plan": {
            "strategy": "single-agent-fast-path",
            "agent_tasks": [
                {
                    "result": {
                        "adapter": {
                            "execution_mode": "remote-worker",
                            "execution_unit_id": "ecs-test",
                            "worker_id": "worker-test",
                            "success": True,
                            "remote_run_id": "run_test",
                            "message": message,
                        }
                    }
                }
            ],
        },
    }


class RemoteE2EValidationTests(unittest.TestCase):
    def test_semantic_evidence_passes(self) -> None:
        message = "代码审计证据：worker.py 存在可靠性风险，建议修复。" * 8

        result = assert_remote_result(
            remote_task(message),
            "ecs-test",
            "worker-test",
            (("worker.py",), ("风险",), ("修复", "建议")),
        )

        self.assertEqual(result["semantic_evidence"], "passed")
        self.assertGreaterEqual(result["response_chars"], 120)

    def test_missing_semantic_evidence_fails(self) -> None:
        message = "执行成功，但是没有给出所要求的代码位置与风险证据。" * 10

        with self.assertRaisesRegex(RuntimeError, "semantic evidence is missing"):
            assert_remote_result(
                remote_task(message),
                "ecs-test",
                "worker-test",
                (("worker.py",), ("修复",)),
            )


if __name__ == "__main__":
    unittest.main()
