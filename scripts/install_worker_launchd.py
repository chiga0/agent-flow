#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import plistlib
import subprocess
from pathlib import Path


LABEL = "com.aflow.worker"


def main() -> int:
    parser = argparse.ArgumentParser(description="Install the aflow macOS worker service")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--no-start", action="store_true")
    parser.add_argument("--uninstall", action="store_true")
    args = parser.parse_args()

    repo = args.repo.expanduser().resolve()
    launch_agents = Path.home() / "Library" / "LaunchAgents"
    plist_path = launch_agents / f"{LABEL}.plist"
    domain = f"gui/{os.getuid()}"
    if args.uninstall:
        subprocess.run(
            ["launchctl", "bootout", domain, str(plist_path)],
            check=False,
            capture_output=True,
        )
        plist_path.unlink(missing_ok=True)
        print(plist_path)
        return 0
    if args.env_file is None:
        parser.error("--env-file is required unless --uninstall is used")
    env_file = args.env_file.expanduser().resolve()
    runner = repo / "scripts" / "run_worker_macos.sh"
    if not (repo / "runtime" / "cloud_agents_runtime" / "worker.py").is_file():
        parser.error(f"not an aflow repository: {repo}")
    if not runner.is_file():
        parser.error(f"missing worker runner: {runner}")
    if not env_file.is_file():
        parser.error(f"missing worker env file: {env_file}")
    if env_file.stat().st_mode & 0o077:
        parser.error(f"worker env file must be chmod 600: {env_file}")

    log_dir = repo / ".aflow" / "logs"
    launch_agents.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "Label": LABEL,
        "ProgramArguments": [str(runner)],
        "WorkingDirectory": str(repo),
        "EnvironmentVariables": {
            "AFLOW_REPO_ROOT": str(repo),
            "AFLOW_WORKER_ENV_FILE": str(env_file),
        },
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 10,
        "StandardOutPath": str(log_dir / "worker.log"),
        "StandardErrorPath": str(log_dir / "worker.error.log"),
    }
    with plist_path.open("wb") as handle:
        plistlib.dump(payload, handle, sort_keys=True)
    os.chmod(plist_path, 0o600)

    if not args.no_start:
        subprocess.run(
            ["launchctl", "bootout", domain, str(plist_path)],
            check=False,
            capture_output=True,
        )
        subprocess.run(
            ["launchctl", "bootstrap", domain, str(plist_path)], check=True
        )
        subprocess.run(["launchctl", "kickstart", "-k", f"{domain}/{LABEL}"], check=True)
    print(plist_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
