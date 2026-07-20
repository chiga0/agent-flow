#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import platform
import secrets
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = ROOT / "deploy" / "docker-compose.runtime.yml"
DEFAULT_ENV_FILE = ROOT / ".env.local"
DEFAULT_DATA_DIR = ROOT / ".aflow" / "local-data"
DEFAULT_URL = "http://127.0.0.1:8765"
REQUIRED_ENV_KEYS = {
    "RUN_MANAGER_TOKEN",
    "RUN_MANAGER_BOOTSTRAP_EMAIL",
    "RUNTIME_BOOTSTRAP_PASSWORD",
    "RUN_MANAGER_SESSION_SECRET",
    "RUNTIME_ARTIFACTS_DIR",
    "V2_LOCAL_EXECUTION_UNIT_ID",
}


class StackError(RuntimeError):
    pass


def main() -> int:
    args = parse_args()
    env_file = args.env_file.expanduser().resolve()
    if args.command == "init":
        init_environment(env_file, bind=args.bind)
        return 0
    if args.command == "doctor":
        doctor()
        return 0
    if args.command == "up":
        init_environment(env_file, bind=args.bind)
        doctor()
        compose(env_file, "up", "-d", *("--build",) if not args.no_build else ())
        env = read_env(env_file)
        wait_until_ready(env)
        verify_execution_unit(env)
        run_smoke(env)
        print_ready(env_file, env)
        return 0
    if args.command == "status":
        env = require_environment(env_file)
        compose(env_file, "ps")
        health(env)
        print("runtime health: ok")
        return 0
    if args.command == "smoke":
        run_smoke(require_environment(env_file))
        return 0
    if args.command == "demo":
        run_demo(
            require_environment(env_file),
            adapter=args.adapter,
            require_real_cli=args.require_real_cli,
            timeout=args.timeout,
        )
        return 0
    if args.command == "logs":
        compose(env_file, "logs", "--tail", str(args.tail), "-f")
        return 0
    if args.command == "down":
        if not env_file.exists():
            print(f"local stack is already down; environment not found: {env_file}")
            return 0
        compose(env_file, "down", "--remove-orphans")
        return 0
    raise StackError(f"unknown command: {args.command}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Initialize and operate the aflow local/NAS runtime profile"
    )
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    subparsers = parser.add_subparsers(dest="command", required=True)
    init = subparsers.add_parser("init", help="create a private local environment file")
    init.add_argument("--bind", default="127.0.0.1")
    up = subparsers.add_parser("up", help="build, start, register, and smoke test")
    up.add_argument("--bind", default="127.0.0.1")
    up.add_argument("--no-build", action="store_true")
    subparsers.add_parser("doctor", help="check local Docker prerequisites")
    subparsers.add_parser("status", help="show container and runtime health")
    subparsers.add_parser("smoke", help="run the fast HTTP control-plane smoke test")
    demo = subparsers.add_parser("demo", help="run a complex multi-agent acceptance case")
    demo.add_argument(
        "--adapter",
        choices=["fake", "qwen", "codex", "claude", "opencode"],
        default="fake",
    )
    demo.add_argument("--require-real-cli", action="store_true")
    demo.add_argument("--timeout", type=int, default=60)
    logs = subparsers.add_parser("logs", help="follow runtime logs")
    logs.add_argument("--tail", type=int, default=200)
    subparsers.add_parser("down", help="stop the local runtime")
    return parser.parse_args()


def init_environment(path: Path, *, bind: str) -> dict[str, str]:
    if path.exists():
        env = read_env(path)
        validate_environment(env)
        try:
            path.chmod(0o600)
        except OSError as exc:
            raise StackError(f"cannot secure environment file {path}: {exc}") from exc
        print(f"environment already exists: {path}")
        return env
    if bind not in {"127.0.0.1", "0.0.0.0"}:
        raise StackError("bind must be 127.0.0.1 or 0.0.0.0")
    data_dir = DEFAULT_DATA_DIR.resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    try:
        data_dir.chmod(0o700)
    except OSError:
        pass
    cpu_count = max(1, os.cpu_count() or 1)
    memory_mb = detected_memory_mb() or 2048
    runtime_memory = max(768, min(4096, memory_mb // 2))
    runtime_cpus = max(1.0, min(4.0, float(cpu_count - 1 or 1)))
    hostname = safe_slug(platform.node() or "local")
    values = {
        "RUN_MANAGER_TOKEN": secrets.token_urlsafe(32),
        "RUN_MANAGER_BOOTSTRAP_EMAIL": "owner@aflow.local",
        "RUNTIME_BOOTSTRAP_PASSWORD": secrets.token_urlsafe(24),
        "RUN_MANAGER_BOOTSTRAP_NAME": "Local Owner",
        "RUN_MANAGER_SESSION_SECRET": secrets.token_urlsafe(32),
        "RUN_MANAGER_WORKER_CAPACITY": "0",
        "RUNTIME_BIND": bind,
        "RUNTIME_ARTIFACTS_DIR": str(data_dir),
        "RUNTIME_CPUS": str(runtime_cpus),
        "RUNTIME_MEMORY_LIMIT": f"{runtime_memory}m",
        "RUNTIME_PIDS_LIMIT": "1024",
        "V2_DEPLOYMENT_PROFILE": "local-nas",
        "V2_ENABLE_REAL_CLI_ADAPTERS": "0",
        "V2_QWEN_CODE_COMMAND": "qwen",
        "V2_CODEX_CLI_COMMAND": "codex exec --skip-git-repo-check -",
        "V2_LOCAL_EXECUTION_UNIT_ID": f"{hostname}-runtime",
        "V2_LOCAL_EXECUTION_UNIT_KIND": "co-located-runtime",
        "V2_LOCAL_EXECUTION_UNIT_LABELS_JSON": json.dumps(
            {"region": "local", "tier": "personal", "host": hostname},
            separators=(",", ":"),
        ),
        "V2_LOCAL_EXECUTION_UNIT_RESOURCES_JSON": json.dumps(
            {"cpu": cpu_count, "memory_mb": memory_mb}, separators=(",", ":")
        ),
        "V2_LOCAL_EXECUTION_UNIT_ADAPTERS": "fake,qwen,codex",
        "V2_LOCAL_EXECUTION_UNIT_FEATURES": "workspace,artifacts,events,cli-adapters",
        "OPENAI_API_KEY": "",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_env(values), encoding="utf-8")
    path.chmod(0o600)
    print(f"created private environment: {path}")
    if bind == "0.0.0.0":
        print("warning: port 8765 is LAN-visible; use a firewall or private VPN")
    return values


def render_env(values: dict[str, str]) -> str:
    lines = ["# Generated by scripts/local_stack.py. Do not commit this file."]
    lines.extend(f"{key}={value}" for key, value in values.items())
    return "\n".join(lines) + "\n"


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def require_environment(path: Path) -> dict[str, str]:
    if not path.exists():
        raise StackError(f"missing {path}; run make local-init or make local-up")
    env = read_env(path)
    validate_environment(env)
    return env


def validate_environment(env: dict[str, str]) -> None:
    missing = sorted(key for key in REQUIRED_ENV_KEYS if not env.get(key))
    if missing:
        raise StackError("environment is missing required values: " + ", ".join(missing))


def doctor() -> None:
    run(["docker", "--version"], capture=True)
    run(["docker", "compose", "version"], capture=True)
    run(["docker", "info"], capture=True)
    cpu_count = os.cpu_count() or 0
    memory_mb = detected_memory_mb()
    print(f"docker: ok; host: {cpu_count or 'unknown'} CPU, {memory_mb or 'unknown'} MB")
    if cpu_count and cpu_count < 4:
        print("warning: fewer than 4 CPUs; keep real CLI concurrency at one")
    if memory_mb and memory_mb < 4096:
        print("warning: less than 4 GB RAM; the deterministic adapter is recommended")


def detected_memory_mb() -> int | None:
    if sys.platform == "darwin":
        result = subprocess.run(
            ["sysctl", "-n", "hw.memsize"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip().isdigit():
            return int(result.stdout.strip()) // 1024 // 1024
    meminfo = Path("/proc/meminfo")
    if meminfo.exists():
        for line in meminfo.read_text(encoding="utf-8").splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) // 1024
    return None


def compose(env_file: Path, *args: str) -> None:
    run(
        [
            "docker",
            "compose",
            "--env-file",
            str(env_file),
            "-f",
            str(COMPOSE_FILE),
            *args,
        ]
    )


def run(command: list[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            cwd=ROOT,
            check=True,
            text=True,
            capture_output=capture,
        )
    except FileNotFoundError as exc:
        raise StackError(f"missing command: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        suffix = f": {detail}" if detail else ""
        raise StackError(f"command failed: {shlex.join(command)}{suffix}") from exc


def api_request(
    env: dict[str, str],
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: int = 10,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        DEFAULT_URL + path,
        data=data,
        method="POST" if data is not None else "GET",
        headers={
            "Authorization": f"Bearer {env['RUN_MANAGER_TOKEN']}",
            "Content-Type": "application/json",
            **(headers or {}),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise StackError(f"{path} returned HTTP {exc.code}: {body}") from exc
    except (urllib.error.URLError, OSError) as exc:
        reason = getattr(exc, "reason", str(exc))
        raise StackError(f"cannot reach {DEFAULT_URL}{path}: {reason}") from exc


def health(env: dict[str, str]) -> dict[str, Any]:
    return api_request(env, "/health")


def wait_until_ready(env: dict[str, str], timeout: int = 120) -> None:
    deadline = time.time() + timeout
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            health(env)
            return
        except StackError as exc:
            last_error = exc
            time.sleep(1)
    raise StackError(f"runtime was not ready after {timeout}s: {last_error}")


def verify_execution_unit(env: dict[str, str]) -> None:
    units = api_request(env, "/v2/admin/execution-units")["units"]
    expected = env["V2_LOCAL_EXECUTION_UNIT_ID"]
    matches = [unit for unit in units if unit["unit_id"] == expected]
    if not matches or matches[0]["status"] != "active":
        raise StackError(f"execution unit {expected} is not active")
    if matches[0]["kind"] != "co-located-runtime":
        raise StackError(f"execution unit {expected} is not co-located with runtime")
    print(f"execution unit: {expected} (active, co-located-runtime)")


def run_smoke(env: dict[str, str]) -> None:
    command = [
        sys.executable,
        str(ROOT / "scripts" / "smoke_v2_control_plane.py"),
        "--base-url",
        DEFAULT_URL,
        "--token",
        env["RUN_MANAGER_TOKEN"],
    ]
    run(command)


def run_demo(
    env: dict[str, str],
    *,
    adapter: str,
    require_real_cli: bool,
    timeout: int,
) -> None:
    goal = (
        "Design, implement, and review a tenant-aware release workflow with rollback, "
        "audit evidence, operational checks, and a concise production handoff. "
        "Separate architecture, implementation, and independent review responsibilities."
    )
    task = api_request(
        env,
        "/v2/tasks",
        {"goal": goal, "mode": "multi-agent", "adapter": adapter, "channel": "web"},
        headers={"Idempotency-Key": f"local-demo-{time.time_ns()}"},
    )
    task_id = task["task_id"]
    deadline = time.time() + timeout
    while time.time() < deadline:
        task = api_request(env, f"/v2/tasks/{task_id}")
        if task["status"] == "completed":
            break
        if task["status"] in {"failed", "cancelled"}:
            raise StackError(f"demo task ended as {task['status']}: {task.get('error')}")
        time.sleep(0.2)
    else:
        raise StackError(f"demo task did not complete within {timeout}s")
    evidence = {
        "events": api_request(env, f"/v2/tasks/{task_id}/events.json")["events"],
        "webshell": api_request(env, f"/v2/tasks/{task_id}/webshell/events.json")[
            "events"
        ],
        "artifacts": api_request(env, f"/v2/tasks/{task_id}/artifacts")["artifacts"],
        "evaluations": api_request(env, f"/v2/tasks/{task_id}/evaluations")[
            "evaluations"
        ],
        "audit": api_request(env, f"/v2/tasks/{task_id}/audit.json"),
    }
    validate_demo(task, evidence, env, require_real_cli=require_real_cli)
    summary = {
        "task_id": task_id,
        "status": task["status"],
        "strategy": task["plan"]["strategy"],
        "execution_unit": task["metadata"]["dispatch"]["execution_unit_id"],
        "adapter": adapter,
        "execution_mode": execution_modes(evidence["artifacts"]),
        "roles": sorted(agent_roles(evidence["events"])),
        "artifacts": len(evidence["artifacts"]),
        "evaluations": len(evidence["evaluations"]),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


def validate_demo(
    task: dict[str, Any],
    evidence: dict[str, Any],
    env: dict[str, str],
    *,
    require_real_cli: bool,
) -> None:
    expected_roles = {"brain", "builder", "reviewer"}
    checks = {
        "task completed": task["status"] == "completed",
        "orchestrator-workers plan": task["plan"]["strategy"] == "orchestrator-workers",
        "three planned roles": {
            item["role"] for item in task["plan"]["agent_tasks"]
        } == expected_roles,
        "configured execution unit": task["metadata"]["dispatch"]["execution_unit_id"]
        == env["V2_LOCAL_EXECUTION_UNIT_ID"],
        "live output for all roles": agent_roles(evidence["events"]) == expected_roles,
        "webshell role projection": webshell_roles(evidence["webshell"])
        == expected_roles,
        "artifact per role": len(evidence["artifacts"]) >= 3,
        "all evaluations passed": bool(evidence["evaluations"])
        and all(item["status"] == "passed" for item in evidence["evaluations"]),
        "audit bundle schema": evidence["audit"].get("schema")
        == "agentflow-v2-task-audit/v1",
    }
    if require_real_cli:
        checks["real CLI execution"] = execution_modes(evidence["artifacts"]) == [
            "real-cli"
        ]
    failures = [name for name, passed in checks.items() if not passed]
    if failures:
        raise StackError("demo acceptance failed: " + ", ".join(failures))


def agent_roles(events: list[dict[str, Any]]) -> set[str]:
    return {
        event["actor"]
        for event in events
        if event.get("type") == "agent.message"
        and event.get("actor") in {"brain", "builder", "reviewer"}
    }


def webshell_roles(events: list[dict[str, Any]]) -> set[str]:
    return {
        event.get("_meta", {}).get("agentRole")
        for event in events
        if event.get("_meta", {}).get("agentRole") in {"brain", "builder", "reviewer"}
    }


def execution_modes(artifacts: list[dict[str, Any]]) -> list[str]:
    return sorted(
        {
            artifact.get("content", {}).get("adapter", {}).get("execution_mode", "unknown")
            for artifact in artifacts
        }
    )


def safe_slug(value: str) -> str:
    slug = "".join(character.lower() if character.isalnum() else "-" for character in value)
    return "-".join(part for part in slug.split("-") if part)[:40] or "local"


def print_ready(env_file: Path, env: dict[str, str]) -> None:
    print(f"aflow is ready: {DEFAULT_URL}")
    print(f"login email: {env['RUN_MANAGER_BOOTSTRAP_EMAIL']}")
    print(f"credentials: {env_file} (mode 0600; password is not printed)")
    print("next: make local-demo")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (StackError, KeyError, ValueError) as exc:
        print(f"local stack failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
