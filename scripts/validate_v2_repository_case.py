#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.cloud_agents_runtime.worker import ControlPlaneClient
from runtime.cloud_agents_runtime.worker import RemoteWorkerConfig
from runtime.cloud_agents_runtime.worker import RemoteWorkerDaemon


GOAL = (
    "Fix the real slug generation defect in this repository. Implement Unicode-aware "
    "normalization so accented text such as 'Café Déjà Vu' becomes 'cafe-deja-vu', "
    "collapse every run of non-alphanumeric characters to one hyphen, trim surrounding "
    "hyphens, and return 'untitled' for empty results. Preserve the existing ASCII "
    "behavior, run the full unittest suite, and update README.md with the exact behavior. "
    "Do not create a git commit; the aflow worker owns verification and delivery."
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="validate a real Agent-backed V2 repository delivery"
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--token", default=os.environ.get("RUN_MANAGER_TOKEN"))
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument(
        "--worker-id", default=f"repository-acceptance-{uuid4().hex[:12]}"
    )
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument(
        "--adapter",
        choices=["qwen", "codex", "claude", "opencode"],
        default="qwen",
    )
    args = parser.parse_args(argv)
    if not args.token:
        parser.error("--token or RUN_MANAGER_TOKEN is required")
    if args.timeout < 60:
        parser.error("--timeout must be at least 60 seconds")
    return args


def run_git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    ).stdout.strip()


def prepare_fixture(work_root: Path) -> tuple[Path, str]:
    case_root = work_root.resolve() / f"case-{uuid4().hex}"
    repo = case_root / "source" / "slug-service"
    repo.mkdir(parents=True, mode=0o700)
    (repo / "slugify.py").write_text(
        "def normalize_slug(value: str) -> str:\n"
        "    return value.strip().lower().replace(' ', '-')\n",
        encoding="utf-8",
    )
    (repo / "test_slugify.py").write_text(
        "import unittest\n\n"
        "from slugify import normalize_slug\n\n\n"
        "class NormalizeSlugTest(unittest.TestCase):\n"
        "    def test_preserves_ascii_behavior(self):\n"
        "        self.assertEqual(normalize_slug('Hello World'), 'hello-world')\n\n"
        "    def test_normalizes_unicode_and_separators(self):\n"
        "        self.assertEqual(\n"
        "            normalize_slug('  Café___Déjà\\tVu!!!  '),\n"
        "            'cafe-deja-vu',\n"
        "        )\n\n"
        "    def test_empty_result_has_stable_fallback(self):\n"
        "        self.assertEqual(normalize_slug('---'), 'untitled')\n\n\n"
        "if __name__ == '__main__':\n"
        "    unittest.main()\n",
        encoding="utf-8",
    )
    (repo / "README.md").write_text(
        "# Slug service\n\n"
        "`normalize_slug` lowercases text and replaces spaces with hyphens.\n",
        encoding="utf-8",
    )
    (repo / ".gitignore").write_text(
        "__pycache__/\n*.py[cod]\n",
        encoding="utf-8",
    )
    subprocess.run(
        ["git", "init", "-b", "main", str(repo)],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    run_git(repo, "add", "-A")
    run_git(
        repo,
        "-c",
        "user.name=aflow acceptance",
        "-c",
        "user.email=acceptance@localhost",
        "commit",
        "-m",
        "seed real slug defect",
    )
    initial_head = run_git(repo, "rev-parse", "HEAD")
    failing = subprocess.run(
        [sys.executable, "-B", "-m", "unittest", "-v"],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if failing.returncode == 0:
        raise RuntimeError("acceptance fixture must reproduce the defect before execution")
    return repo, initial_head


def changed_files_from_patch(patch: str) -> set[str]:
    files: set[str] = set()
    for line in patch.splitlines():
        if not line.startswith("diff --git a/"):
            continue
        before, _separator, _after = line.removeprefix("diff --git a/").partition(" b/")
        if before:
            files.add(before)
    return files


def validate_delivery(
    *,
    client: ControlPlaneClient,
    task: dict[str, object],
    repo: Path,
    initial_head: str,
) -> dict[str, object]:
    task_id = str(task["task_id"])
    if task.get("status") != "completed":
        status = task.get("status")
        raise RuntimeError(f"repository task ended as {status}: {task.get('result')}")
    if task.get("execution_mode") != "real-cli":
        raise RuntimeError(
            f"repository task used {task.get('execution_mode')}, expected real-cli"
        )
    if task.get("goal") != GOAL or task.get("mode") != "single":
        raise RuntimeError("repository task did not preserve the requested goal/mode")

    artifact_payload = client.request_json(f"/v2/tasks/{task_id}/artifacts")
    artifacts = artifact_payload.get("artifacts") or []
    by_name = {
        str(item["name"]): item
        for item in artifacts
        if isinstance(item, dict) and item.get("name")
    }
    required = {"worker_execution", "test_results", "git_patch", "git_commit"}
    missing = sorted(required - set(by_name))
    if missing:
        raise RuntimeError(f"repository task is missing artifacts: {missing}")

    tests = by_name["test_results"].get("content") or {}
    if tests.get("passed") is not True or tests.get("exit_code") != 0:
        raise RuntimeError("repository verification did not pass")
    patch = by_name["git_patch"].get("content") or {}
    changed_files = changed_files_from_patch(str(patch.get("text") or ""))
    if "slugify.py" not in changed_files or "README.md" not in changed_files:
        changed_summary = ", ".join(sorted(changed_files))
        raise RuntimeError(
            "repository delivery must change implementation and documentation: "
            f"{changed_summary}"
        )
    if len(changed_files) < 2:
        raise RuntimeError("repository delivery changed fewer than two files")
    generated_files = sorted(
        path
        for path in changed_files
        if "__pycache__" in Path(path).parts or Path(path).suffix == ".pyc"
    )
    if generated_files:
        raise RuntimeError(f"repository delivery included generated files: {generated_files}")
    commit = by_name["git_commit"].get("content") or {}
    commit_hash = str(commit.get("hash") or "")
    branch = str(commit.get("branch") or "")
    if len(commit_hash) != 40 or not branch.startswith("aflow/"):
        raise RuntimeError("repository delivery is missing its managed commit or branch")

    event_types = [
        str(item.get("type"))
        for item in task.get("events") or []
        if isinstance(item, dict)
    ]
    for required_event in ("workspace.prepared", "agent.message", "task.completed"):
        if required_event not in event_types:
            raise RuntimeError(f"repository task is missing event {required_event}")
    audit = client.request_json(f"/v2/tasks/{task_id}/audit.json")
    if audit.get("schema") != "agentflow-v2-task-audit/v1":
        raise RuntimeError("repository task audit bundle is invalid")
    if run_git(repo, "rev-parse", "HEAD") != initial_head:
        raise RuntimeError("source checkout HEAD changed during repository execution")
    if run_git(repo, "status", "--porcelain"):
        raise RuntimeError("source checkout working tree changed during repository execution")

    return {
        "task_id": task_id,
        "status": task["status"],
        "execution_mode": task["execution_mode"],
        "changed_files": sorted(changed_files),
        "test_command": tests.get("command"),
        "test_passed": tests.get("passed"),
        "commit": commit_hash,
        "branch": branch,
        "source_head_unchanged": True,
        "event_types": sorted(set(event_types)),
        "artifact_names": sorted(by_name),
        "audit_schema": audit["schema"],
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo, initial_head = prepare_fixture(args.work_root)
    client = ControlPlaneClient(args.base_url, token=args.token, timeout_seconds=15)
    worker = RemoteWorkerDaemon(
        RemoteWorkerConfig(
            control_url=args.base_url,
            token=args.token,
            worker_id=args.worker_id,
            capacity=1,
            lease_ttl_seconds=60,
            poll_interval_seconds=1,
            heartbeat_interval_seconds=5,
            run_wait_timeout_seconds=args.timeout,
            artifact_root=args.work_root.resolve() / "worker",
            metadata={"acceptance": "real-repository-v1"},
        )
    )
    client.v2_heartbeat(
        args.worker_id,
        {
            "kind": "remote-worker",
            "status": "active",
            "lease_ttl_seconds": 60,
            "labels": {"acceptance": "real-repository-v1"},
            "resources": {},
            "adapters": [args.adapter],
            "features": ["artifacts", "events", "v2-agent-tasks"],
        },
    )
    task = client.request_json(
        "/v2/tasks",
        method="POST",
        payload={
            "goal": GOAL,
            "mode": "single",
            "adapter": args.adapter,
            "channel": "web",
            "metadata": {"acceptance": "real-repository-v1"},
            "workspace": {
                "execution_unit_id": args.worker_id,
                "source_path": str(repo),
                "ref": "HEAD",
                "test_command": [sys.executable, "-B", "-m", "unittest", "-v"],
                "require_changes": True,
            },
        },
    )
    print(f"repository case requirement: {GOAL}", flush=True)
    print(f"repository case source: {repo}", flush=True)
    print(f"repository case task: {task['task_id']}", flush=True)

    deadline = time.monotonic() + args.timeout + 30
    completed = task
    while time.monotonic() < deadline:
        claimed = worker.run_once(wait=True)
        completed = client.request_json(f"/v2/tasks/{task['task_id']}")
        if completed.get("status") in {"completed", "failed", "cancelled"}:
            break
        if not claimed:
            time.sleep(1)
    evidence = validate_delivery(
        client=client,
        task=completed,
        repo=repo,
        initial_head=initial_head,
    )
    print("repository case evidence: " + json.dumps(evidence, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
