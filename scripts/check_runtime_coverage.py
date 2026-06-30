#!/usr/bin/env python3
from __future__ import annotations

import ast
import pathlib
import sys
import threading
import trace
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNTIME_ROOT = ROOT / "runtime" / "cloud_agents_runtime"
TEST_ROOT = ROOT / "runtime" / "tests"
MIN_COVERAGE = 90.0


def main() -> int:
    sys.path.insert(0, str(ROOT))
    runner = trace.Trace(count=True, trace=False, ignoredirs=[sys.prefix, sys.exec_prefix])
    threading.settrace(runner.globaltrace)
    result = runner.runfunc(run_tests)
    threading.settrace(None)
    if not result.wasSuccessful():
        return 1

    counts = runner.results().counts
    executable = executable_lines()
    normalized_counts = {
        (pathlib.Path(filename).resolve(), lineno): count
        for (filename, lineno), count in counts.items()
    }
    covered = {}
    for path in executable:
        covered[path] = {
            lineno
            for (filename, lineno), count in normalized_counts.items()
            if filename == path and count
        }
    total_lines = sum(len(lines) for lines in executable.values())
    covered_lines = sum(len(executable[path] & covered.get(path, set())) for path in executable)
    percent = (covered_lines / total_lines * 100.0) if total_lines else 100.0
    print(f"runtime coverage: {percent:.2f}% ({covered_lines}/{total_lines})")
    if percent < MIN_COVERAGE:
        print(f"coverage below {MIN_COVERAGE:.1f}%", file=sys.stderr)
        for path, lines in sorted(executable.items()):
            missing = sorted(lines - covered.get(path, set()))
            if missing:
                relative = path.relative_to(ROOT)
                print(f"missing {relative}: {missing[:40]}", file=sys.stderr)
        return 1
    return 0


def run_tests() -> unittest.result.TestResult:
    suite = unittest.defaultTestLoader.discover(str(TEST_ROOT))
    return unittest.TextTestRunner(verbosity=2).run(suite)


def executable_lines() -> dict[pathlib.Path, set[int]]:
    result: dict[pathlib.Path, set[int]] = {}
    for path in sorted(RUNTIME_ROOT.rglob("*.py")):
        if path.name == "__main__.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        lines: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.stmt) and hasattr(node, "lineno"):
                lines.add(node.lineno)
        result[path.resolve()] = lines
    return result


if __name__ == "__main__":
    raise SystemExit(main())
