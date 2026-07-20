#!/usr/bin/env python3
from __future__ import annotations

import ast
import gc
import pathlib
import sys
import threading
import trace
import unittest
import warnings


ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNTIME_ROOT = ROOT / "runtime" / "cloud_agents_runtime"
TEST_ROOT = ROOT / "runtime" / "tests"
MIN_COVERAGE = 90.0


def main() -> int:
    sys.path.insert(0, str(ROOT))
    coverage_counts = collect_with_coverage()
    if coverage_counts is None:
        coverage_counts = collect_with_trace()

    return report_coverage(coverage_counts)


def collect_with_coverage() -> dict[pathlib.Path, set[int]] | None:
    try:
        import coverage
    except ModuleNotFoundError:
        return None

    cov = coverage.Coverage(source=[str(RUNTIME_ROOT)], concurrency=["thread"])
    cov.start()
    result = run_tests()
    cov.stop()
    if not result.wasSuccessful():
        raise SystemExit(1)

    data = cov.get_data()
    covered = {
        path.resolve(): set(data.lines(str(path)) or [])
        for path in executable_lines()
    }
    cov.erase()
    return covered


def collect_with_trace() -> dict[pathlib.Path, set[int]]:
    runner = trace.Trace(count=True, trace=False, ignoredirs=[sys.prefix, sys.exec_prefix])
    threading.settrace(runner.globaltrace)
    result = runner.runfunc(run_tests)
    threading.settrace(None)
    if not result.wasSuccessful():
        raise SystemExit(1)

    counts = runner.results().counts
    normalized_counts = {
        (pathlib.Path(filename).resolve(), lineno): count
        for (filename, lineno), count in counts.items()
    }
    return {
        path: {
            lineno
            for (filename, lineno), count in normalized_counts.items()
            if filename == path and count
        }
        for path in executable_lines()
    }


def report_coverage(covered: dict[pathlib.Path, set[int]]) -> int:
    executable = executable_lines()
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
    unclosed_resources: list[str] = []
    previous_hook = sys.unraisablehook

    def record_unraisable(args: sys.UnraisableHookArgs) -> None:
        if isinstance(args.exc_value, ResourceWarning):
            unclosed_resources.append(str(args.exc_value))
            return
        previous_hook(args)

    sys.unraisablehook = record_unraisable
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", ResourceWarning)
            suite = unittest.defaultTestLoader.discover(str(TEST_ROOT))
            result = unittest.TextTestRunner(verbosity=2).run(suite)
            gc.collect()
    finally:
        sys.unraisablehook = previous_hook
    if unclosed_resources:
        details = "\n".join(sorted(set(unclosed_resources)))
        raise RuntimeError(f"unclosed runtime resources detected:\n{details}")
    return result


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
