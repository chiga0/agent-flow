from __future__ import annotations

import argparse
import codecs
from collections import deque
import json
import os
import queue
import shlex
import shutil
import signal
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .adapters import FakeAdapter, QwenServeAdapter, RuntimeAdapter
from .models import RunSpec, RunState


TERMINAL_EVENTS = {"run.completed", "run.failed", "run.cancelled"}


@dataclass(frozen=True)
class RemoteWorkerConfig:
    control_url: str
    token: str | None = None
    worker_id: str = field(default_factory=socket.gethostname)
    capacity: int = 1
    lease_ttl_seconds: int = 60
    poll_interval_seconds: float = 2.0
    heartbeat_interval_seconds: float = 10.0
    request_timeout_seconds: float = 10.0
    run_wait_timeout_seconds: float = 300.0
    artifact_root: Path | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ActiveRunContext:
    run: RunState
    adapter: RuntimeAdapter
    store: RemoteWorkerRunStore
    applied_controls: set[str] = field(default_factory=set)


@dataclass
class ActiveAgentContext:
    assignment: dict[str, Any]
    process: subprocess.Popen[str] | None = None
    cancelled: threading.Event = field(default_factory=threading.Event)
    applied_permissions: set[str] = field(default_factory=set)


class WorkspaceVerificationError(RuntimeError):
    def __init__(self, result: dict[str, Any]):
        self.result = result
        super().__init__(
            f"workspace verification failed with code {result['exit_code']}: "
            f"{str(result.get('output') or '')[-800:]}"
        )


class ControlPlaneClient:
    def __init__(
        self,
        base_url: str,
        *,
        token: str | None = None,
        timeout_seconds: float = 10.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout_seconds = timeout_seconds

    def heartbeat(self, worker_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.request_json(
            f"/workers/{quote_path(worker_id)}/heartbeat",
            method="POST",
            payload=payload,
        )

    def claim(self, worker_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.request_json(
            f"/workers/{quote_path(worker_id)}/claim",
            method="POST",
            payload=payload,
        )

    def control(self, worker_id: str) -> dict[str, Any]:
        return self.request_json(f"/workers/{quote_path(worker_id)}/control")

    def append_event(
        self,
        worker_id: str,
        run_id: str,
        event_type: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        return self.request_json(
            f"/workers/{quote_path(worker_id)}/runs/{quote_path(run_id)}/events",
            method="POST",
            payload={"type": event_type, "data": data},
        )

    def upload_artifact(
        self,
        worker_id: str,
        run_id: str,
        name: str,
        *,
        content: str | None = None,
        json_value: Any | None = None,
        mode: str = "write",
        chunk_index: int | None = None,
        final: bool | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"name": name}
        if mode != "write":
            payload["mode"] = mode
        if chunk_index is not None:
            payload["chunk_index"] = chunk_index
        if final is not None:
            payload["final"] = final
        if json_value is not None:
            payload["json"] = json_value
        elif content is not None:
            payload["content"] = content
        else:
            payload["content"] = ""
        return self.request_json(
            f"/workers/{quote_path(worker_id)}/runs/{quote_path(run_id)}/artifacts",
            method="POST",
            payload=payload,
        )

    def v2_heartbeat(self, worker_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.request_json(
            f"/v2/workers/{quote_path(worker_id)}/heartbeat",
            method="POST",
            payload=payload,
        )

    def v2_claim(self, worker_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.request_json(
            f"/v2/workers/{quote_path(worker_id)}/claim",
            method="POST",
            payload=payload,
        )

    def v2_control(self, worker_id: str) -> dict[str, Any]:
        return self.request_json(f"/v2/workers/{quote_path(worker_id)}/control")

    def v2_agent_event(
        self,
        worker_id: str,
        agent_task_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return self.request_json(
            f"/v2/workers/{quote_path(worker_id)}/agent-tasks/{quote_path(agent_task_id)}/events",
            method="POST",
            payload=payload,
        )

    def v2_finish_agent(
        self,
        worker_id: str,
        agent_task_id: str,
        action: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if action not in {"complete", "fail"}:
            raise ValueError("unsupported V2 agent action")
        return self.request_json(
            f"/v2/workers/{quote_path(worker_id)}/agent-tasks/{quote_path(agent_task_id)}/{action}",
            method="POST",
            payload=payload,
        )

    def request_json(
        self,
        path: str,
        *,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"accept": "application/json"}
        if payload is not None:
            headers["content-type"] = "application/json"
        if self.token:
            headers["authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                parsed = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{method} {path} failed: {exc.code} {detail}") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError(f"{method} {path} returned non-object JSON")
        return parsed


class RemoteWorkerRunStore:
    def __init__(
        self,
        client: ControlPlaneClient,
        *,
        worker_id: str,
        run: RunState,
        artifact_root: Path | None = None,
    ):
        self.client = client
        self.worker_id = worker_id
        self.run = run
        self.artifact_root = artifact_root
        self._lock = threading.RLock()
        self._terminal = threading.Event()
        self._prompt_count = run.prompt_count
        self._raw_events: list[dict[str, Any]] = []
        self._status = run.status

    def set_adapter_run_id(self, run_id: str, adapter_run_id: str) -> None:
        self._require_run(run_id)
        with self._lock:
            self.run.adapter_run_id = adapter_run_id
        self.append_event(
            run_id,
            "adapter.run_id",
            {"adapter_run_id": adapter_run_id},
        )

    def increment_prompt_count(self, run_id: str) -> int:
        self._require_run(run_id)
        with self._lock:
            self._prompt_count += 1
            self.run.prompt_count = self._prompt_count
            return self._prompt_count

    def write_json(self, run_id: str, name: str, payload: dict[str, Any]) -> Path:
        self._require_run(run_id)
        self.client.upload_artifact(self.worker_id, run_id, name, json_value=payload)
        if self.artifact_root:
            path = safe_child_file(self.artifact_root / run_id, name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            return path
        return Path(name)

    def append_raw_event(self, run_id: str, adapter: str, payload: dict[str, Any]) -> None:
        self._require_run(run_id)
        with self._lock:
            raw_event = {
                "adapter": adapter,
                "payload": payload,
                "index": len(self._raw_events) + 1,
            }
            self._raw_events.append(raw_event)
            content = json.dumps(raw_event, ensure_ascii=False) + "\n"
            chunk_index = raw_event["index"]
            if self.artifact_root:
                path = safe_child_file(self.artifact_root / run_id, "raw_events.jsonl")
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8") as file:
                    file.write(content)
        self.client.upload_artifact(
            self.worker_id,
            run_id,
            "raw_events.jsonl",
            content=content,
            mode="append",
            chunk_index=chunk_index,
        )

    def append_event(
        self,
        run_id: str,
        event_type: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._require_run(run_id)
        payload = dict(data or {})
        event = self.client.append_event(self.worker_id, run_id, event_type, payload)
        with self._lock:
            if event_type == "run.started":
                self._status = "running"
            elif event_type == "run.completed":
                self._status = "completed"
            elif event_type == "run.failed":
                self._status = "failed"
            elif event_type == "run.cancelled":
                self._status = "cancelled"
            self.run.status = self._status
            if event_type in TERMINAL_EVENTS:
                self._terminal.set()
        return event

    def is_terminal(self, run_id: str) -> bool:
        self._require_run(run_id)
        return self._terminal.is_set() or self._status in {"completed", "failed", "cancelled"}

    def wait_terminal(self, timeout_seconds: float | None = None) -> bool:
        return self._terminal.wait(timeout_seconds)

    def _require_run(self, run_id: str) -> None:
        if run_id != self.run.run_id:
            raise KeyError(run_id)


class RemoteWorkerDaemon:
    def __init__(
        self,
        config: RemoteWorkerConfig,
        *,
        client: ControlPlaneClient | None = None,
        adapters: dict[str, RuntimeAdapter] | None = None,
    ):
        self.config = config
        self.client = client or ControlPlaneClient(
            config.control_url,
            token=config.token,
            timeout_seconds=config.request_timeout_seconds,
        )
        self.adapters = adapters or default_adapters()
        self._stop = threading.Event()
        self._active: list[threading.Thread] = []
        self._active_lock = threading.Lock()
        self._active_agents: dict[str, ActiveAgentContext] = {}
        self._last_v2_cleanup = 0.0

    def stop(self) -> None:
        self._stop.set()

    def run_forever(self) -> None:
        while not self._stop.is_set():
            self.claim_once()
            self._stop.wait(self.config.poll_interval_seconds)

    def run_once(self, *, wait: bool = False) -> bool:
        thread = self.claim_once()
        if thread and wait:
            thread.join(self.config.run_wait_timeout_seconds + 5)
        return thread is not None

    def claim_once(self) -> threading.Thread | None:
        self._reap_finished()
        self._cleanup_expired_v2_workspaces()
        if self._active_count() >= self.config.capacity:
            self.client.heartbeat(self.config.worker_id, self._worker_payload())
            return None
        v2_payload = self._v2_worker_payload()
        self.client.v2_heartbeat(self.config.worker_id, v2_payload)
        v2_claim = self.client.v2_claim(self.config.worker_id, v2_payload)
        assignment = v2_claim.get("assignment")
        if isinstance(assignment, dict):
            agent_task_id = str(assignment["agent_task_id"])
            context = ActiveAgentContext(assignment=assignment)
            with self._active_lock:
                self._active_agents[agent_task_id] = context
            thread = threading.Thread(
                target=self._execute_agent_task,
                args=(context,),
                name=f"remote-agent-{agent_task_id}",
                daemon=True,
            )
            with self._active_lock:
                self._active.append(thread)
            thread.start()
            return thread

        claim = self.client.claim(self.config.worker_id, self._worker_payload())
        run_payload = claim.get("run")
        if not isinstance(run_payload, dict):
            return None
        run = run_state_from_payload(run_payload)
        thread = threading.Thread(
            target=self._execute_run,
            args=(run,),
            name=f"remote-worker-{run.run_id}",
            daemon=True,
        )
        with self._active_lock:
            self._active.append(thread)
        thread.start()
        return thread

    def _execute_agent_task(self, context: ActiveAgentContext) -> None:
        assignment = context.assignment
        agent_task_id = str(assignment["agent_task_id"])
        lease_token = str(assignment["lease_token"])
        adapter = str(assignment.get("adapter") or "fake")
        protocol = "internal" if adapter == "fake" else "ACP/A2A"
        workspace = self._agent_workspace(assignment)
        workspace_manifest: dict[str, Any] = {}
        heartbeat_stop = threading.Event()
        heartbeat = threading.Thread(
            target=self._v2_heartbeat_loop,
            args=(heartbeat_stop, context),
            name=f"remote-agent-heartbeat-{agent_task_id}",
            daemon=True,
        )
        heartbeat.start()
        try:
            workspace, workspace_manifest = self._prepare_agent_workspace(assignment)
            self.client.v2_agent_event(
                self.config.worker_id,
                agent_task_id,
                {
                    "lease_token": lease_token,
                    "type": "workspace.prepared",
                    "payload": workspace_manifest,
                },
            )
            envelope = {
                "protocol": "agentflow-v2-acp-a2a",
                "protocol_version": "2026-07",
                "task_id": assignment["task_id"],
                "agent_task_id": agent_task_id,
                "role": assignment.get("role"),
                "adapter": adapter,
                "goal": assignment.get("goal"),
                "context": {
                    "depends_on": assignment.get("depends_on") or [],
                    "artifact_contract": assignment.get("artifact_contract") or {},
                    "workspace": workspace_manifest,
                },
            }
            if adapter == "fake":
                summary = (
                    f"{assignment.get('role') or 'agent'} completed: "
                    f"{assignment.get('goal') or ''}"
                )
                execution_mode = "fake"
                exit_code = 0
            else:
                summary, execution_mode, exit_code = self._run_v2_cli(
                    context, envelope, workspace
                )
            if context.cancelled.is_set():
                raise RuntimeError("cancelled by control plane")
            verification = self._run_workspace_verification(context, workspace)
            delivery = self._finalize_git_workspace(assignment, workspace)
            artifacts = [
                {
                    "name": "worker_execution",
                    "kind": "metadata",
                    "content": {
                        **workspace_manifest,
                        "attempt": assignment.get("attempt"),
                    },
                }
            ]
            if verification:
                artifacts.append(
                    {"name": "test_results", "kind": "test", "content": verification}
                )
            if delivery:
                artifacts.extend(
                    [
                        {"name": "git_patch", "kind": "patch", "content": delivery["patch"]},
                        {"name": "git_commit", "kind": "git", "content": delivery["commit"]},
                    ]
                )
            self.client.v2_finish_agent(
                self.config.worker_id,
                agent_task_id,
                "complete",
                {
                    "lease_token": lease_token,
                    "summary": summary,
                    "protocol": protocol,
                    "execution_mode": execution_mode,
                    "exit_code": exit_code,
                    "artifacts": artifacts,
                },
            )
        except Exception as exc:  # noqa: BLE001 - report execution failures
            artifacts = []
            if isinstance(exc, WorkspaceVerificationError):
                artifacts.append(
                    {"name": "test_results", "kind": "test", "content": exc.result}
                )
            try:
                self.client.v2_finish_agent(
                    self.config.worker_id,
                    agent_task_id,
                    "fail",
                    {
                        "lease_token": lease_token,
                        "error": str(exc),
                        "retryable": not context.cancelled.is_set(),
                        "artifacts": artifacts,
                        "workspace": workspace_manifest,
                    },
                )
            except Exception:
                pass
        finally:
            heartbeat_stop.set()
            heartbeat.join(timeout=2)
            with self._active_lock:
                self._active_agents.pop(agent_task_id, None)

    def _run_v2_cli(
        self,
        context: ActiveAgentContext,
        envelope: dict[str, Any],
        workspace: Path,
    ) -> tuple[str, str, int]:
        adapter = str(context.assignment["adapter"])
        command_env = {
            "qwen": "V2_QWEN_CODE_COMMAND",
            "codex": "V2_CODEX_CLI_COMMAND",
            "claude": "V2_CLAUDE_CODE_COMMAND",
            "opencode": "V2_OPENCODE_COMMAND",
        }.get(adapter)
        defaults = {
            "qwen": "qwen",
            "codex": "codex exec --skip-git-repo-check -",
            "claude": "claude -p",
            "opencode": "opencode run",
        }
        command = shlex.split(os.environ.get(command_env or "", defaults.get(adapter, "")))
        executable = shutil.which(command[0]) if command else None
        if os.environ.get("V2_ENABLE_REAL_CLI_ADAPTERS") != "1" or not executable:
            if isinstance(context.assignment.get("workspace"), dict) and context.assignment[
                "workspace"
            ].get("source_path"):
                raise RuntimeError(
                    f"{adapter} real CLI is required for repository tasks"
                )
            return (
                f"{adapter} protocol simulation completed for {envelope['goal']}",
                "protocol-simulated",
                0,
            )
        process = subprocess.Popen(
            [executable, *command[1:]],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=workspace,
            env=self._sanitized_worker_env(),
            start_new_session=True,
        )
        context.process = process
        assert process.stdin is not None and process.stdout is not None
        process.stdin.write(json.dumps(envelope, ensure_ascii=False))
        process.stdin.close()
        timeout = max(1, int(os.environ.get("V2_AGENT_TIMEOUT_SECONDS") or 3600))
        summary, exit_code, truncated = self._stream_agent_process(
            context,
            process,
            timeout_seconds=timeout,
            message_prefix="",
            execution_mode="real-cli",
        )
        if truncated:
            summary = f"[earlier output truncated]\n{summary}"
        summary = summary.strip() or f"{adapter} completed with code {exit_code}"
        if exit_code != 0:
            raise RuntimeError(f"{adapter} CLI exited with code {exit_code}: {summary[:400]}")
        return summary[:4000], "real-cli", exit_code

    def _stream_agent_process(
        self,
        context: ActiveAgentContext,
        process: subprocess.Popen[str],
        *,
        timeout_seconds: int,
        message_prefix: str,
        execution_mode: str,
    ) -> tuple[str, int, bool]:
        assert process.stdout is not None
        lines: queue.Queue[str | None] = queue.Queue(maxsize=256)

        def read_output() -> None:
            try:
                decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
                while raw_chunk := os.read(process.stdout.fileno(), 4096):
                    chunk = decoder.decode(raw_chunk)
                    if chunk:
                        lines.put(chunk)
                final_chunk = decoder.decode(b"", final=True)
                if final_chunk:
                    lines.put(final_chunk)
            finally:
                lines.put(None)

        reader = threading.Thread(target=read_output, name="agent-output", daemon=True)
        reader.start()
        deadline = time.monotonic() + timeout_seconds
        max_bytes = max(4096, int(os.environ.get("V2_MAX_COMMAND_OUTPUT_BYTES") or 262144))
        tail: deque[tuple[str, int]] = deque()
        tail_bytes = 0
        truncated = False
        event_lines = 0
        max_event_lines = max(
            1, int(os.environ.get("V2_MAX_COMMAND_EVENT_LINES") or 5000)
        )
        try:
            while True:
                if context.cancelled.is_set():
                    self._terminate_agent_process(process)
                    raise RuntimeError("cancelled by control plane")
                if time.monotonic() >= deadline:
                    self._terminate_agent_process(process)
                    raise TimeoutError(
                        f"{execution_mode} timed out after {timeout_seconds} seconds"
                    )
                try:
                    line = lines.get(timeout=0.2)
                except queue.Empty:
                    if process.poll() is not None and not reader.is_alive():
                        break
                    continue
                if line is None:
                    break
                for output_line in line.splitlines() or [line]:
                    if not output_line:
                        continue
                    output_line = self._redact_worker_output(output_line)
                    encoded_size = len(
                        output_line.encode("utf-8", errors="replace")
                    ) + 1
                    tail.append((output_line, encoded_size))
                    tail_bytes += encoded_size
                    while tail and tail_bytes > max_bytes:
                        _removed, removed_size = tail.popleft()
                        tail_bytes -= removed_size
                        truncated = True
                    if event_lines >= max_event_lines:
                        truncated = True
                        continue
                    event_lines += 1
                    message = f"{message_prefix}{output_line[:760]}"
                    if event_lines == max_event_lines:
                        message += " [event stream limit reached]"
                    self.client.v2_agent_event(
                        self.config.worker_id,
                        str(context.assignment["agent_task_id"]),
                        {
                            "lease_token": context.assignment["lease_token"],
                            "type": "agent.message",
                            "payload": {
                                "message": message,
                                "protocol": "ACP/A2A",
                                "execution_mode": execution_mode,
                                "partial": True,
                            },
                        },
                    )
            return "\n".join(line for line, _size in tail), process.wait(), truncated
        finally:
            if process.poll() is None:
                self._terminate_agent_process(process)
            process.stdout.close()
            context.process = None

    @staticmethod
    def _terminate_agent_process(process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (OSError, ProcessLookupError):
                process.kill()
            process.wait(timeout=3)

    def _v2_heartbeat_loop(
        self,
        stop: threading.Event,
        context: ActiveAgentContext,
    ) -> None:
        while not stop.is_set() and not self._stop.is_set():
            try:
                self.client.v2_heartbeat(self.config.worker_id, self._v2_worker_payload())
                control = self.client.v2_control(self.config.worker_id)
                for action in control.get("actions") or []:
                    if (
                        isinstance(action, dict)
                        and action.get("agent_task_id") == context.assignment.get("agent_task_id")
                        and action.get("type") == "cancel"
                    ):
                        context.cancelled.set()
                        if context.process is not None and context.process.poll() is None:
                            self._terminate_agent_process(context.process)
                for permission in control.get("permissions") or []:
                    if not isinstance(permission, dict):
                        continue
                    if permission.get("agent_task_id") != context.assignment.get(
                        "agent_task_id"
                    ):
                        continue
                    permission_id = str(permission.get("permission_id") or "")
                    if not permission_id or permission_id in context.applied_permissions:
                        continue
                    context.applied_permissions.add(permission_id)
                    self.client.v2_agent_event(
                        self.config.worker_id,
                        str(context.assignment["agent_task_id"]),
                        {
                            "lease_token": context.assignment["lease_token"],
                            "type": "permission.applied",
                            "payload": {
                                "permission_id": permission_id,
                                "decision": permission.get("decision") or {},
                            },
                        },
                    )
            except Exception:
                pass
            stop.wait(self.config.heartbeat_interval_seconds)

    def _agent_workspace(self, assignment: dict[str, Any]) -> Path:
        root = self.config.artifact_root or Path(".aflow-worker")
        task_id = safe_path_segment(str(assignment["task_id"]))
        agent_task_id = safe_path_segment(str(assignment["agent_task_id"]))
        attempt = max(1, int(assignment.get("attempt") or 1))
        return root.resolve() / "v2" / task_id / agent_task_id / f"attempt-{attempt}"

    def _prepare_agent_workspace(
        self, assignment: dict[str, Any]
    ) -> tuple[Path, dict[str, Any]]:
        destination = self._agent_workspace(assignment)
        contract = assignment.get("workspace")
        if not isinstance(contract, dict) or not contract.get("source_path"):
            destination.mkdir(parents=True, exist_ok=True, mode=0o700)
            manifest = {
                "strategy": "isolated-directory",
                "path": str(destination),
            }
            self._write_workspace_manifest(destination, manifest)
            return destination, manifest

        bound_worker = str(contract.get("execution_unit_id") or "").strip()
        if bound_worker and bound_worker != self.config.worker_id:
            raise PermissionError(
                f"workspace is bound to {bound_worker}, not {self.config.worker_id}"
            )

        source = Path(str(contract["source_path"])).expanduser().resolve()
        allowed_roots = workspace_roots_from_env()
        if not allowed_roots:
            raise RuntimeError(
                "V2_WORKSPACE_ROOTS must allow the requested repository root"
            )
        if not any(path_is_within(source, root) for root in allowed_roots):
            raise PermissionError(f"workspace source is outside V2_WORKSPACE_ROOTS: {source}")
        if not source.is_dir():
            raise ValueError(f"workspace source is not a directory: {source}")
        git_head = git_worker_output(source, "rev-parse", str(contract.get("ref") or "HEAD"))
        git_worker_output(source, "rev-parse", "--is-inside-work-tree")
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if destination.exists():
            raise RuntimeError(f"workspace already exists: {destination}")
        branch = workspace_branch_name(assignment)
        subprocess.run(
            [
                "git",
                "-C",
                str(source),
                "worktree",
                "add",
                "-b",
                branch,
                str(destination),
                git_head,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        manifest = {
            "strategy": "git-worktree",
            "path": str(destination),
            "source_path": str(source),
            "ref": str(contract.get("ref") or "HEAD"),
            "base_commit": git_head,
            "branch": branch,
        }
        self._write_workspace_manifest(destination, manifest)
        return destination, manifest

    def _write_workspace_manifest(
        self, destination: Path, manifest: dict[str, Any]
    ) -> None:
        payload = {**manifest, "created_at_epoch": time.time()}
        workspace_manifest_path(destination).write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        workspace_manifest_path(destination).chmod(0o600)

    def _cleanup_expired_v2_workspaces(self) -> None:
        now = time.time()
        interval = max(
            1, int(os.environ.get("V2_WORKSPACE_CLEANUP_INTERVAL_SECONDS") or 3600)
        )
        if now - self._last_v2_cleanup < interval:
            return
        self._last_v2_cleanup = now
        retention = max(
            0, int(os.environ.get("V2_WORKSPACE_RETENTION_SECONDS") or 604800)
        )
        branch_retention = max(
            retention,
            int(os.environ.get("V2_BRANCH_RETENTION_SECONDS") or 2592000),
        )
        root = (self.config.artifact_root or Path(".aflow-worker")).resolve() / "v2"
        if not root.is_dir():
            return
        with self._active_lock:
            active_paths = {
                self._agent_workspace(context.assignment).resolve()
                for context in self._active_agents.values()
            }
        for manifest_path in root.rglob("attempt-*.workspace.json"):
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                destination = Path(str(manifest["path"])).resolve()
                destination.relative_to(root)
                if destination in active_paths:
                    continue
                created_at = float(
                    manifest.get("created_at_epoch") or manifest_path.stat().st_mtime
                )
                age = now - created_at
                if manifest.get("strategy") == "git-worktree":
                    source = Path(str(manifest["source_path"])).resolve()
                    branch = str(manifest.get("branch") or "")
                    if not branch.startswith("aflow/"):
                        continue
                    if destination.exists() and age >= retention:
                        subprocess.run(
                            [
                                "git",
                                "-C",
                                str(source),
                                "worktree",
                                "remove",
                                "--force",
                                str(destination),
                            ],
                            check=True,
                            capture_output=True,
                            text=True,
                            timeout=60,
                        )
                        manifest["worktree_removed_at_epoch"] = now
                        manifest_path.write_text(
                            json.dumps(manifest, ensure_ascii=False, sort_keys=True),
                            encoding="utf-8",
                        )
                    if age >= branch_retention and not destination.exists():
                        deleted = subprocess.run(
                            ["git", "-C", str(source), "branch", "-D", branch],
                            check=False,
                            capture_output=True,
                            text=True,
                            timeout=60,
                        )
                        exists = subprocess.run(
                            [
                                "git",
                                "-C",
                                str(source),
                                "show-ref",
                                "--verify",
                                "--quiet",
                                f"refs/heads/{branch}",
                            ],
                            check=False,
                            timeout=60,
                        )
                        if deleted.returncode == 0 or exists.returncode == 1:
                            manifest_path.unlink(missing_ok=True)
                elif age >= retention:
                    if destination.exists():
                        shutil.rmtree(destination)
                    manifest_path.unlink(missing_ok=True)
            except (
                OSError,
                ValueError,
                KeyError,
                json.JSONDecodeError,
                subprocess.SubprocessError,
            ):
                continue

    def _run_workspace_verification(
        self, context: ActiveAgentContext, workspace: Path
    ) -> dict[str, Any]:
        contract = context.assignment.get("workspace")
        command_value = contract.get("test_command") if isinstance(contract, dict) else None
        if not command_value:
            return {}
        command = command_value if isinstance(command_value, list) else shlex.split(command_value)
        if not command:
            raise ValueError("workspace test command is empty")
        timeout = max(1, int(os.environ.get("V2_WORKSPACE_TEST_TIMEOUT_SECONDS") or 1800))
        process = subprocess.Popen(
            command,
            cwd=workspace,
            env=self._sanitized_worker_env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
        context.process = process
        output, exit_code, truncated = self._stream_agent_process(
            context,
            process,
            timeout_seconds=timeout,
            message_prefix="[verify] ",
            execution_mode="workspace-verification",
        )
        result = {
            "command": command,
            "exit_code": exit_code,
            "output": output[-20000:],
            "output_truncated": truncated or len(output) > 20000,
            "passed": exit_code == 0,
        }
        if exit_code != 0:
            raise WorkspaceVerificationError(result)
        return result

    def _finalize_git_workspace(
        self, assignment: dict[str, Any], workspace: Path
    ) -> dict[str, dict[str, Any]]:
        contract = assignment.get("workspace")
        if not isinstance(contract, dict) or not contract.get("source_path"):
            return {}
        status = git_worker_output(workspace, "status", "--short")
        subprocess.run(
            ["git", "-C", str(workspace), "add", "-A"],
            check=True,
            capture_output=True,
            text=True,
        )
        max_patch_bytes = max(1024, int(os.environ.get("V2_MAX_PATCH_BYTES") or 1048576))
        patch, patch_bytes, truncated = git_worker_output_limited(
            workspace,
            max_patch_bytes,
            "diff",
            "--cached",
            "--binary",
        )
        if patch_bytes == 0 and contract.get("require_changes", True):
            raise RuntimeError("agent completed without producing repository changes")
        commit_hash = ""
        if patch_bytes:
            message = f"aflow: {str(assignment.get('goal') or 'agent task')[:72]}"
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(workspace),
                    "-c",
                    "user.name=aflow",
                    "-c",
                    "user.email=aflow@localhost",
                    "commit",
                    "-m",
                    message,
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            commit_hash = git_worker_output(workspace, "rev-parse", "HEAD")
        return {
            "patch": {
                "text": patch,
                "bytes": patch_bytes,
                "truncated": truncated,
                "status_before_commit": status,
            },
            "commit": {
                "hash": commit_hash,
                "branch": workspace_branch_name(assignment),
                "base_commit": git_worker_output(workspace, "rev-parse", "HEAD^")
                if commit_hash
                else git_worker_output(workspace, "rev-parse", "HEAD"),
                "workspace": str(workspace),
            },
        }

    def _sanitized_worker_env(self) -> dict[str, str]:
        allowed_prefixes = ("V2_", "QWEN_", "CODEX_", "ANTHROPIC_", "OPENAI_", "OPENCODE_")
        allowed_names = {"PATH", "HOME", "LANG", "LC_ALL", "TERM", "TMPDIR"}
        return {
            key: value
            for key, value in os.environ.items()
            if key in allowed_names or key.startswith(allowed_prefixes)
        }

    @staticmethod
    def _redact_worker_output(value: str) -> str:
        redacted = value
        secret_markers = ("KEY", "TOKEN", "SECRET", "PASSWORD")
        for key, secret in os.environ.items():
            if len(secret) >= 8 and any(marker in key.upper() for marker in secret_markers):
                redacted = redacted.replace(secret, "[REDACTED]")
        return redacted

    def _execute_run(self, run: RunState) -> None:
        store = RemoteWorkerRunStore(
            self.client,
            worker_id=self.config.worker_id,
            run=run,
            artifact_root=self.config.artifact_root,
        )
        heartbeat_stop = threading.Event()
        adapter = self.adapters.get(run.spec.adapter)
        if adapter is None:
            store.append_event(
                run.run_id,
                "run.failed",
                {"reason": f"unknown adapter: {run.spec.adapter}"},
            )
            return
        context = ActiveRunContext(run=run, adapter=adapter, store=store)
        heartbeat = threading.Thread(
            target=self._heartbeat_loop,
            args=(heartbeat_stop, context),
            name=f"remote-worker-heartbeat-{run.run_id}",
            daemon=True,
        )
        heartbeat.start()
        try:
            adapter.start(run, store)  # type: ignore[arg-type]
            if run.spec.prompt and not store.is_terminal(run.run_id):
                adapter.send_input(run, run.spec.prompt, store)  # type: ignore[arg-type]
            timeout = run.spec.timeout_seconds or self.config.run_wait_timeout_seconds
            deadline = time.monotonic() + timeout
            while not store.is_terminal(run.run_id):
                self._apply_control(self._fetch_control(), context)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                store.wait_terminal(min(1.0, remaining))
            if not store.is_terminal(run.run_id):
                adapter.cancel(run, "remote worker timeout", store)  # type: ignore[arg-type]
                store.wait_terminal(5)
        except Exception as exc:  # noqa: BLE001 - surface worker failures to control plane
            if not store.is_terminal(run.run_id):
                store.append_event(
                    run.run_id,
                    "run.failed",
                    {"reason": str(exc), "worker_id": self.config.worker_id},
                )
        finally:
            heartbeat_stop.set()
            heartbeat.join(timeout=2)

    def _heartbeat_loop(
        self,
        stop: threading.Event,
        context: ActiveRunContext | None = None,
    ) -> None:
        while not stop.is_set() and not self._stop.is_set():
            response = self.client.heartbeat(self.config.worker_id, self._worker_payload())
            control = control_from_response(response)
            if isinstance(control, dict) and context is not None:
                self._apply_control(control, context)
            stop.wait(self.config.heartbeat_interval_seconds)

    def _fetch_control(self) -> dict[str, Any]:
        try:
            return self.client.control(self.config.worker_id)
        except Exception:
            return {}

    def _apply_control(
        self,
        control: dict[str, Any] | None,
        context: ActiveRunContext,
    ) -> None:
        if not control or context.store.is_terminal(context.run.run_id):
            return
        runs = control.get("runs")
        if not isinstance(runs, list):
            return
        for item in runs:
            if not isinstance(item, dict) or item.get("run_id") != context.run.run_id:
                continue
            cancel_event = item.get("cancel")
            if isinstance(cancel_event, dict):
                control_id = str(cancel_event.get("id") or cancel_event.get("sequence"))
                if control_id not in context.applied_controls:
                    context.applied_controls.add(control_id)
                    data = cancel_event.get("data")
                    reason = None
                    if isinstance(data, dict):
                        reason = data.get("reason")
                    context.adapter.cancel(
                        context.run,
                        str(reason or "cancelled by control plane"),
                        context.store,  # type: ignore[arg-type]
                    )
            resolutions = item.get("permission_resolutions")
            if not isinstance(resolutions, list):
                continue
            for event in resolutions:
                if not isinstance(event, dict):
                    continue
                control_id = str(event.get("id") or event.get("sequence"))
                if control_id in context.applied_controls:
                    continue
                data = event.get("data")
                if not isinstance(data, dict):
                    continue
                permission_id = data.get("permission_id")
                payload = data.get("payload")
                if not isinstance(permission_id, str) or not isinstance(payload, dict):
                    continue
                context.applied_controls.add(control_id)
                context.adapter.resolve_permission(
                    context.run,
                    permission_id,
                    payload,
                    context.store,  # type: ignore[arg-type]
                )

    def _worker_payload(self) -> dict[str, Any]:
        metadata = dict(self.config.metadata)
        metadata.setdefault("hostname", socket.gethostname())
        metadata.setdefault("resources", host_resource_capacity())
        raw_metrics = metadata.get("metrics")
        metrics = dict(raw_metrics) if isinstance(raw_metrics, dict) else {}
        metrics.update(host_resource_metrics())
        metadata["metrics"] = metrics
        raw_capabilities = metadata.get("capabilities")
        capabilities = dict(raw_capabilities) if isinstance(raw_capabilities, dict) else {}
        raw_features = capabilities.get("features")
        extra_features = raw_features if isinstance(raw_features, list) else []
        capabilities["adapters"] = sorted(self.adapters)
        capabilities["features"] = sorted(
            {*extra_features, "artifacts", "claim", "control", "events", "heartbeat"}
        )
        metadata["capabilities"] = capabilities
        return {
            "kind": "remote",
            "capacity": self.config.capacity,
            "lease_ttl_seconds": self.config.lease_ttl_seconds,
            "metadata": metadata,
        }

    def _v2_worker_payload(self) -> dict[str, Any]:
        payload = self._worker_payload()
        metadata = dict(payload.get("metadata") or {})
        capabilities = dict(metadata.get("capabilities") or {})
        configured_adapters = [
            item.strip()
            for item in os.environ.get(
                "V2_WORKER_ADAPTERS", "fake,qwen,codex,claude,opencode"
            ).split(",")
            if item.strip()
        ]
        return {
            "kind": "remote-worker",
            "status": "active",
            "lease_ttl_seconds": self.config.lease_ttl_seconds,
            "labels": metadata,
            "resources": metadata.get("resources") or {},
            "adapters": configured_adapters,
            "features": [*(capabilities.get("features") or []), "v2-agent-tasks"],
        }

    def _active_count(self) -> int:
        with self._active_lock:
            return sum(1 for thread in self._active if thread.is_alive())

    def _reap_finished(self) -> None:
        with self._active_lock:
            self._active = [thread for thread in self._active if thread.is_alive()]


def default_adapters() -> dict[str, RuntimeAdapter]:
    return {
        "fake": FakeAdapter(),
        "qwen": QwenServeAdapter(
            base_url=os.environ.get("QWEN_SERVE_URL"),
            token=os.environ.get("QWEN_SERVE_TOKEN"),
        ),
    }


def run_state_from_payload(payload: dict[str, Any]) -> RunState:
    spec = RunSpec.from_payload(dict(payload.get("spec") or {}))
    return RunState(
        run_id=str(payload["run_id"]),
        spec=spec,
        status=str(payload.get("status") or "created"),
        adapter_run_id=payload.get("adapter_run_id"),
        created_at=str(payload.get("created_at") or ""),
        updated_at=str(payload.get("updated_at") or ""),
        event_count=int(payload.get("event_count") or 0),
        prompt_count=int(payload.get("prompt_count") or 0),
    )


def control_from_response(response: dict[str, Any]) -> dict[str, Any] | None:
    control = response.get("control")
    if isinstance(control, dict):
        return control
    worker = response.get("worker")
    if isinstance(worker, dict) and isinstance(worker.get("control"), dict):
        return worker["control"]
    return None


def safe_child_file(parent: Path, name: str) -> Path:
    candidate = Path(name)
    if candidate.name != name or name in {"", ".", ".."}:
        raise ValueError("artifact name must be a file name")
    return parent / name


def safe_path_segment(value: str) -> str:
    if not value or value in {".", ".."} or Path(value).name != value:
        raise ValueError("identifier is not a safe path segment")
    return value


def workspace_roots_from_env() -> list[Path]:
    raw = os.environ.get("V2_WORKSPACE_ROOTS") or ""
    return [
        Path(item.strip()).expanduser().resolve()
        for item in raw.split(os.pathsep)
        if item.strip()
    ]


def path_is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def workspace_branch_name(assignment: dict[str, Any]) -> str:
    task_id = safe_path_segment(str(assignment["task_id"]))
    agent_task_id = safe_path_segment(str(assignment["agent_task_id"]))
    attempt = max(1, int(assignment.get("attempt") or 1))
    return f"aflow/{task_id}/{agent_task_id}/attempt-{attempt}"


def workspace_manifest_path(destination: Path) -> Path:
    return destination.parent / f"{destination.name}.workspace.json"


def git_worker_output(path: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(path), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def git_worker_output_limited(
    path: Path, max_bytes: int, *args: str
) -> tuple[str, int, bool]:
    process = subprocess.Popen(
        ["git", "-C", str(path), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    assert process.stdout is not None
    kept = bytearray()
    total = 0
    while chunk := process.stdout.read(65536):
        total += len(chunk)
        if len(kept) < max_bytes:
            kept.extend(chunk[: max_bytes - len(kept)])
    process.stdout.close()
    exit_code = process.wait()
    if exit_code != 0:
        raise subprocess.CalledProcessError(
            exit_code,
            process.args,
            output=bytes(kept),
        )
    return kept.decode("utf-8", errors="replace").strip(), total, total > max_bytes


def quote_path(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def parse_json_object(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("metadata must be a JSON object")
    return parsed


def host_resource_capacity() -> dict[str, Any]:
    resources: dict[str, Any] = {"cpus": os.cpu_count() or 1}
    memory_total = linux_meminfo_kb().get("MemTotal")
    if memory_total:
        resources["memory_gb"] = round(memory_total / 1024 / 1024, 2)
    return resources


def host_resource_metrics() -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    cpu_count = max(1, os.cpu_count() or 1)
    try:
        load_average = os.getloadavg()[0]
    except (AttributeError, OSError):
        load_average = None
    if load_average is not None:
        metrics["load_average"] = round(load_average, 2)
        metrics["cpu_percent"] = min(100.0, round((load_average / cpu_count) * 100, 1))
    meminfo = linux_meminfo_kb()
    memory_total = meminfo.get("MemTotal")
    memory_available = meminfo.get("MemAvailable")
    if memory_total and memory_available is not None:
        used = max(0, memory_total - memory_available)
        metrics["memory_percent"] = round((used / memory_total) * 100, 1)
    swap_total = meminfo.get("SwapTotal")
    swap_free = meminfo.get("SwapFree")
    if swap_total and swap_free is not None:
        used_swap = max(0, swap_total - swap_free)
        metrics["swap_percent"] = round((used_swap / swap_total) * 100, 1)
    try:
        disk = shutil.disk_usage("/")
    except OSError:
        disk = None
    if disk and disk.total:
        metrics["disk_percent"] = round((disk.used / disk.total) * 100, 1)
    return metrics


def linux_meminfo_kb() -> dict[str, int]:
    path = Path("/proc/meminfo")
    if not path.exists():
        return {}
    values: dict[str, int] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            key, _, rest = line.partition(":")
            if not key or not rest:
                continue
            amount = rest.strip().split()[0]
            if amount.isdigit():
                values[key] = int(amount)
    except OSError:
        return {}
    return values


def positive_int(value: int | None, default: int) -> int:
    if value is None:
        return default
    return max(0, value)


def positive_float(value: float | None, default: float) -> float:
    if value is None:
        return default
    return max(0.0, value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="aflow remote worker")
    parser.add_argument(
        "--control-url",
        default=os.environ.get("RUN_WORKER_CONTROL_URL"),
        help="aflow Runtime control-plane base URL",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("RUN_WORKER_TOKEN") or os.environ.get("RUN_MANAGER_TOKEN"),
        help="bearer token for the control plane",
    )
    parser.add_argument(
        "--worker-id",
        default=os.environ.get("RUN_WORKER_ID") or socket.gethostname(),
        help="stable worker id",
    )
    parser.add_argument(
        "--capacity",
        type=int,
        default=int(os.environ.get("RUN_WORKER_CAPACITY") or "1"),
        help="maximum active runs on this worker",
    )
    parser.add_argument(
        "--lease-ttl-seconds",
        type=int,
        default=int(os.environ.get("RUN_WORKER_LEASE_TTL_SECONDS") or "60"),
    )
    parser.add_argument(
        "--poll-interval-seconds",
        type=float,
        default=float(os.environ.get("RUN_WORKER_POLL_INTERVAL_SECONDS") or "2"),
    )
    parser.add_argument(
        "--heartbeat-interval-seconds",
        type=float,
        default=float(os.environ.get("RUN_WORKER_HEARTBEAT_INTERVAL_SECONDS") or "10"),
    )
    parser.add_argument(
        "--run-wait-timeout-seconds",
        type=float,
        default=float(os.environ.get("RUN_WORKER_RUN_WAIT_TIMEOUT_SECONDS") or "300"),
    )
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=(
            Path(os.environ["RUN_WORKER_ARTIFACT_ROOT"])
            if os.environ.get("RUN_WORKER_ARTIFACT_ROOT")
            else None
        ),
        help="optional local mirror directory for worker artifacts",
    )
    parser.add_argument(
        "--metadata-json",
        default=os.environ.get("RUN_WORKER_METADATA_JSON"),
        help="additional worker metadata JSON object",
    )
    parser.add_argument("--once", action="store_true", help="claim at most one run and exit")
    args = parser.parse_args(argv)
    if not args.control_url:
        parser.error("--control-url or RUN_WORKER_CONTROL_URL is required")
    config = RemoteWorkerConfig(
        control_url=args.control_url,
        token=args.token,
        worker_id=args.worker_id,
        capacity=positive_int(args.capacity, 1),
        lease_ttl_seconds=positive_int(args.lease_ttl_seconds, 60),
        poll_interval_seconds=positive_float(args.poll_interval_seconds, 2.0),
        heartbeat_interval_seconds=positive_float(args.heartbeat_interval_seconds, 10.0),
        run_wait_timeout_seconds=positive_float(args.run_wait_timeout_seconds, 300.0),
        artifact_root=args.artifact_root,
        metadata=parse_json_object(args.metadata_json),
    )
    worker = RemoteWorkerDaemon(config)
    print(f"remote worker {config.worker_id} -> {config.control_url}")
    print(f"capacity: {config.capacity}")
    if args.once:
        return 0 if worker.run_once(wait=True) else 0
    try:
        worker.run_forever()
    except KeyboardInterrupt:
        print("\nremote worker shutting down")
        worker.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
