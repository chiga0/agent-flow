from __future__ import annotations

from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts.validate_v2_repository_case import changed_files_from_patch
from scripts.validate_v2_repository_case import main
from scripts.validate_v2_repository_case import prepare_fixture
from runtime.tests.test_runtime_server import running_runtime


class ValidateV2RepositoryCaseTest(unittest.TestCase):
    def test_main_delivers_isolated_repository_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            command = root / "qwen-test-adapter"
            command.write_text(
                "#!/bin/sh\n"
                "cat >/dev/null\n"
                "cat > slugify.py <<'PY'\n"
                "import re\n"
                "import unicodedata\n\n"
                "def normalize_slug(value: str) -> str:\n"
                "    normalized = unicodedata.normalize('NFKD', value)\n"
                "    ascii_value = ''.join(c for c in normalized if not "
                "unicodedata.combining(c))\n"
                "    slug = re.sub(r'[^a-z0-9]+', '-', ascii_value.lower()).strip('-')\n"
                "    return slug or 'untitled'\n"
                "PY\n"
                "printf '# Slug service\\n\\nUnicode text and separator runs are "
                "normalized into stable slugs.\\n' > README.md\n"
                "printf 'repository defect fixed\\n'\n",
                encoding="utf-8",
            )
            command.chmod(0o755)
            output = io.StringIO()
            with running_runtime(
                artifact_root=root / "control", token="secret", worker_capacity=0
            ) as base_url:
                with patch.dict(
                    os.environ,
                    {
                        "V2_ENABLE_REAL_CLI_ADAPTERS": "1",
                        "V2_WORKER_ADAPTERS": "qwen",
                        "V2_WORKSPACE_ROOTS": str(root),
                        "V2_QWEN_CODE_COMMAND": str(command),
                    },
                ), redirect_stdout(output):
                    self.assertEqual(
                        main(
                            [
                                "--base-url",
                                base_url,
                                "--token",
                                "secret",
                                "--work-root",
                                str(root / "cases"),
                                "--worker-id",
                                "repository-test-worker",
                                "--timeout",
                                "60",
                            ]
                        ),
                        0,
                    )

            evidence = output.getvalue()
            self.assertIn("repository case task: task_", evidence)
            self.assertIn('"execution_mode": "real-cli"', evidence)
            self.assertIn('"source_head_unchanged": true', evidence)

    def test_fixture_reproduces_real_defect_without_dirtying_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo, initial_head = prepare_fixture(Path(tmp))

            self.assertEqual(
                subprocess.run(
                    ["git", "-C", str(repo), "rev-parse", "HEAD"],
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.strip(),
                initial_head,
            )
            self.assertEqual(
                subprocess.run(
                    ["git", "-C", str(repo), "status", "--porcelain"],
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout,
                "",
            )

    def test_changed_files_are_read_from_binary_safe_patch_headers(self) -> None:
        patch = (
            "diff --git a/slugify.py b/slugify.py\n"
            "diff --git a/README.md b/README.md\n"
        )

        self.assertEqual(changed_files_from_patch(patch), {"slugify.py", "README.md"})


if __name__ == "__main__":
    unittest.main()
