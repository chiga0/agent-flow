#!/usr/bin/env python3
from __future__ import annotations

import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
CHECK_DIRS = [ROOT / "runtime", ROOT / "scripts", ROOT / "deploy", ROOT / ".github"]
MAX_LINE_LENGTH = 100


def main() -> int:
    failures: list[str] = []
    for path in iter_files():
        text = path.read_text(encoding="utf-8")
        if "\t" in text:
            failures.append(f"{relative(path)} contains tab characters")
        if text and not text.endswith("\n"):
            failures.append(f"{relative(path)} missing trailing newline")
        for number, line in enumerate(text.splitlines(), start=1):
            if line.rstrip() != line:
                failures.append(f"{relative(path)}:{number} trailing whitespace")
            if len(line) > MAX_LINE_LENGTH:
                failures.append(f"{relative(path)}:{number} line longer than {MAX_LINE_LENGTH}")
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    return 0


def iter_files() -> list[pathlib.Path]:
    files: list[pathlib.Path] = []
    for directory in CHECK_DIRS:
        for path in directory.rglob("*"):
            if "__pycache__" in path.parts or path.name.endswith(".pyc"):
                continue
            if path.suffix in {".py", ".md", ".service", ".yml", ".yaml", ".sh"}:
                files.append(path)
    return sorted(files)


def relative(path: pathlib.Path) -> str:
    return str(path.relative_to(ROOT))


if __name__ == "__main__":
    raise SystemExit(main())
