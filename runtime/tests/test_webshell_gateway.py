from __future__ import annotations

import unittest

from runtime.cloud_agents_runtime.webshell_gateway import (
    extract_prompt,
    find_agent,
    session_context,
    workspace_cwd,
)


class WebShellGatewayTest(unittest.TestCase):
    def test_workspace_and_prompt_validation_edges(self) -> None:
        task = {
            "task_id": "task-1",
            "title": "Fallback agent",
            "status": "running",
            "metadata": {"workspace": {"source_path": " /workspace/repo "}},
        }
        self.assertEqual(workspace_cwd(task), "/workspace/repo")
        self.assertEqual(find_agent(task, "task-1")["role"], "agent")
        self.assertEqual(session_context(task, "task-1")["workspaceCwd"], "/workspace/repo")
        self.assertEqual(
            extract_prompt(
                {
                    "prompt": [
                        {"type": "image", "text": "ignored"},
                        {"type": "text", "text": "first"},
                        {"type": "text", "text": "second"},
                    ]
                }
            ),
            "first\nsecond",
        )
        with self.assertRaises(ValueError):
            extract_prompt({"prompt": "not-a-list"})
        with self.assertRaises(ValueError):
            extract_prompt({"prompt": [{"type": "image"}]})
        with self.assertRaises(KeyError):
            find_agent(task, "missing")


if __name__ == "__main__":
    unittest.main()
