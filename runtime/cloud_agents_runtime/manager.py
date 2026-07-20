from __future__ import annotations

import json
import os
import socket
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .access import AccessManager
from .adapters import FakeAdapter, QwenServeAdapter, RuntimeAdapter
from .budget import BudgetConfig, CostManager
from .cleanup import CleanupManager, CleanupPolicy
from .events import RuntimeEvent, TERMINAL_RUN_EVENTS
from .executors import ExecutorConfig, ExecutorRegistry
from .missions import MissionManager
from .models import RunSpec, RunState
from .notifications import PermissionNotifier
from .ops import BetaOpsConfig, OperationsManager
from .resources import ResourceLimitConfig, ResourcePolicyResolver
from .store import RunStore
from .ui_projection import project_events
from .v2_control_plane import V2ControlPlane
from .workspace import WorkspaceAllocator


MAX_REMOTE_ARTIFACT_BYTES = 2 * 1024 * 1024


class RunManager:
    def __init__(
        self,
        artifact_root: Path,
        adapters: dict[str, RuntimeAdapter] | None = None,
        qwen_base_url: str | None = None,
        qwen_token: str | None = None,
        worker_id: str | None = None,
        worker_capacity: int | None = None,
        lease_ttl_seconds: int | None = None,
        permission_stall_seconds: int | None = None,
        permission_stall_action: str | None = None,
        ops_config: BetaOpsConfig | None = None,
        budget_config: BudgetConfig | None = None,
        resource_config: ResourceLimitConfig | None = None,
        cleanup_policy: CleanupPolicy | None = None,
        heartbeat_enabled: bool = False,
    ):
        self.store = RunStore(artifact_root)
        self.v2 = V2ControlPlane(artifact_root / "v2")
        self.executor_registry = ExecutorRegistry(self.store, ExecutorConfig.from_env())
        self.workspace_allocator = WorkspaceAllocator(artifact_root)
        self.resource_resolver = ResourcePolicyResolver(resource_config)
        self.cleanup_manager = CleanupManager(self.store, cleanup_policy)
        self.ops = OperationsManager(self.store, ops_config)
        self.cost = CostManager(self.store, budget_config)
        self.permission_notifier = PermissionNotifier()
        self.access = AccessManager(
            self.store,
            os.environ.get("RUN_MANAGER_DEFAULT_PRINCIPAL") or "single-tenant-operator",
        )
        self.missions = MissionManager(self)
        self.adapters = adapters or {
            "fake": FakeAdapter(),
            "qwen": QwenServeAdapter(
                base_url=qwen_base_url,
                token=qwen_token,
                executor_registry=self.executor_registry,
            ),
        }
        self.worker_id = worker_id or os.environ.get("RUN_MANAGER_WORKER_ID")
        if not self.worker_id:
            self.worker_id = f"{socket.gethostname()}:{os.getpid()}"
        self.worker_capacity = positive_int(
            worker_capacity,
            os.environ.get("RUN_MANAGER_WORKER_CAPACITY"),
            default=1,
        )
        self.lease_ttl_seconds = positive_int(
            lease_ttl_seconds,
            os.environ.get("RUN_MANAGER_LEASE_TTL_SECONDS"),
            default=60,
        )
        self.permission_stall_seconds = positive_int(
            permission_stall_seconds,
            os.environ.get("RUN_MANAGER_PERMISSION_STALL_SECONDS"),
            default=300,
        )
        self.permission_stall_action = normalize_permission_stall_action(
            permission_stall_action or os.environ.get("RUN_MANAGER_PERMISSION_STALL_ACTION")
        )
        self._scheduler_lock = threading.Lock()
        self._run_threads: list[threading.Thread] = []
        self._run_threads_lock = threading.Lock()
        self._stop = threading.Event()
        self._closed = False
        self.store.add_event_listener(self._on_event)
        self.store.fail_orphaned_jobs_for_worker(
            self.worker_id,
            "runtime restarted without active run thread",
        )
        self.store.register_worker(
            self.worker_id,
            self.worker_capacity,
            self.lease_ttl_seconds,
        )
        self.store.recover_expired_leases()
        self.store.prune_stale_workers(self.ops.config.stale_worker_seconds)
        self._heartbeat_thread: threading.Thread | None = None
        self._cleanup_thread: threading.Thread | None = None
        if heartbeat_enabled:
            self._heartbeat_thread = threading.Thread(
                target=self._heartbeat_loop,
                name=f"runtime-worker-heartbeat-{self.worker_id}",
                daemon=True,
            )
            self._heartbeat_thread.start()
        if self.cleanup_manager.policy.enabled:
            self._cleanup_thread = threading.Thread(
                target=self._cleanup_loop,
                name=f"runtime-cleanup-{self.worker_id}",
                daemon=True,
            )
            self._cleanup_thread.start()
        self._drain_queue()
        self.missions.reconcile()

    def capabilities(self) -> dict[str, Any]:
        return {
            "v": 1,
            "mode": "saeu-run-manager-poc",
            "features": [
                "run_create",
                "run_input",
                "run_events_sse",
                "run_cancel",
                "artifact_files",
                "permission_resolution",
                "permission_notification_gateway",
                "durable_event_store",
                "run_replay",
                "event_gap_detection",
                "runtime_adapter_capabilities",
                "run_queue",
                "run_leases",
                "worker_heartbeat",
                "worker_capacity",
                "per_run_workspace",
                "resource_policy",
                "run_timeout_watchdog",
                "cleanup_policy",
                "profile_registry",
                "mission_task_dag",
                "mission_supervisor",
                "artifact_handoff",
                "reviewer_gate",
                "reviewer_gate_override",
                "merge_deploy_gate",
                "mission_final_report",
                "acp_jsonrpc_poc",
                "a2a_gateway_poc",
                "temporal_workflow_plan_poc",
                "metrics",
                "backup",
                "failure_drills",
                "p5_evaluation_registry",
                "stale_worker_detection",
                "executor_registry",
                "per_run_qwen_executor",
                "container_qwen_executor",
                "remote_worker_registry",
                "remote_worker_claim_api",
                "remote_worker_control_plane",
                "remote_worker_draining",
                "execution_unit_registration",
                "access_project_registry",
                "api_token_registry",
                "cost_budget",
                "daemon_event_projection",
                "session_events",
                "webshell_compatible_bff",
                "task_workspace_bff",
            ],
            "ui_projection": {
                "protocol": "qwen-daemon-compatible",
                "version": "agentflow-ui-projection-v1",
                "routes": {
                    "create_session": "/session",
                    "send_prompt": "/session/{id}/prompt",
                    "events": "/session/{id}/events",
                    "cancel": "/session/{id}/cancel",
                    "permission": "/session/{id}/permission/{requestId}",
                },
            },
            "task_workspace": {
                "protocol": "agentflow-task-workspace-v1",
                "routes": {
                    "list_tasks": "/tasks",
                    "create_task": "/tasks",
                    "task": "/tasks/{id}",
                    "events": "/tasks/{id}/events.json",
                    "artifacts": "/tasks/{id}/artifacts",
                    "result": "/tasks/{id}/result",
                    "messages": "/tasks/{id}/messages",
                    "cancel": "/tasks/{id}/cancel",
                },
            },
            "resource_limits": self.resource_resolver.config.to_dict(),
            "cleanup_policy": self.cleanup_manager.policy.to_dict(),
            "ops_policy": self.ops.config.to_dict(),
            "cost_policy": self.cost.config.to_dict(),
            "permission_notification_policy": self.permission_notifier.config.to_dict(),
            "executor_registry": self.executor_registry.capabilities(),
            "permission_stall_policy": {
                "seconds": self.permission_stall_seconds,
                "action": self.permission_stall_action,
            },
            "queue": self.queue_status(),
            "profiles": [profile.to_dict() for profile in self.store.list_profiles()],
            "adapters": {
                name: adapter.capabilities() for name, adapter in sorted(self.adapters.items())
            },
        }

    def create_run(self, spec: RunSpec) -> RunState:
        self._adapter(spec.adapter)
        run_id = f"run_{uuid4().hex}"
        resource_policy = self.resource_resolver.resolve(spec)
        cost_quote = self.cost.require_allowed(spec)
        spec.metadata["cost_quote"] = cost_quote
        allocation = self.workspace_allocator.prepare(run_id, spec)
        run = self.store.create_run(spec, run_id=run_id)
        self.store.write_json(run.run_id, "workspace.json", allocation.to_dict())
        self.store.append_event(run.run_id, "workspace.prepared", allocation.to_dict())
        self.store.write_json(run.run_id, "resources.json", resource_policy.to_dict())
        self.store.append_event(run.run_id, "resources.resolved", resource_policy.to_dict())
        self.store.write_json(run.run_id, "cost.json", cost_quote)
        self.store.append_event(run.run_id, "cost.quoted", cost_quote)
        self.store.enqueue_run(run.run_id)
        self._drain_queue()
        return self.store.get_run(run.run_id) or run

    def list_tasks(
        self,
        access_context: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        tasks = [
            self._task_from_mission_snapshot(mission)
            for mission in self.list_missions()
        ]
        tasks.extend(self._task_from_run(run) for run in self.store.list_runs())
        tasks = [
            task
            for task in tasks
            if task_access_allowed(task.get("access"), access_context)
        ]
        return sorted(tasks, key=lambda task: task["updated_at"], reverse=True)

    def get_task(
        self,
        task_id: str,
        access_context: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if task_id.startswith("mission_"):
            mission = self.get_mission(task_id)
            task = self._task_from_mission_snapshot(mission) if mission else None
            if task and task_access_allowed(task.get("access"), access_context):
                return task
            return None
        run = self.get_run(task_id)
        task = self._task_from_run(run) if run else None
        if task and task_access_allowed(task.get("access"), access_context):
            return task
        return None

    def create_task(
        self,
        payload: dict[str, Any],
        access_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        goal = payload.get("goal") or payload.get("prompt")
        if not isinstance(goal, str) or not goal.strip():
            raise ValueError("goal is required")
        mode = str(payload.get("mode") or payload.get("task_type") or "single").lower()
        task_metadata = task_access_metadata(payload, access_context)
        if mode in {"mission", "orchestrated", "plan"}:
            mission = self.create_mission(
                {
                    "goal": goal.strip(),
                    "strategy": payload.get("strategy") or "sequential",
                    "adapter": payload.get("adapter") or "fake",
                    "repo": payload.get("repo"),
                    "workspace": payload.get("workspace"),
                    "model": payload.get("model"),
                    "sandbox": payload.get("sandbox") or {},
                    "timeout_seconds": payload.get("timeout_seconds"),
                    "metadata": {
                        **dict(payload.get("metadata") or {}),
                        **task_metadata,
                        "created_from": "task_workspace",
                    },
                    "tasks": payload.get("tasks") or [],
                }
            )
            return self._task_from_mission_snapshot(mission)

        run_payload = {
            "prompt": goal.strip(),
            "adapter": payload.get("adapter") or "fake",
            "repo": payload.get("repo"),
            "workspace": payload.get("workspace"),
            "model": payload.get("model"),
            "sandbox": payload.get("sandbox") or {},
            "timeout_seconds": payload.get("timeout_seconds"),
            "metadata": {
                **dict(payload.get("metadata") or {}),
                **task_metadata,
                "created_from": "task_workspace",
                "task_title": payload.get("title") or first_line(goal),
            },
        }
        run = self.create_run(RunSpec.from_payload(run_payload))
        return self._task_from_run(run)

    def cancel_task(
        self,
        task_id: str,
        reason: str | None = None,
        access_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        task = self.get_task(task_id, access_context=access_context)
        if task is None:
            raise KeyError(task_id)
        if task_id.startswith("mission_"):
            return self._task_from_mission_snapshot(self.cancel_mission(task_id, reason))
        self.cancel(task_id, reason)
        run = self._require_run(task_id)
        return self._task_from_run(run)

    def send_task_message(
        self,
        task_id: str,
        message: str,
        access_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        task = self.get_task(task_id, access_context=access_context)
        if task is None:
            raise KeyError(task_id)
        if task_id.startswith("mission_"):
            raise ValueError("mission tasks do not accept direct follow-up messages yet")
        self.send_input(task_id, message)
        return {"accepted": True, "task_id": task_id, "run_id": task_id}

    def task_events(
        self,
        task_id: str,
        access_context: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        if self.get_task(task_id, access_context=access_context) is None:
            raise KeyError(task_id)
        if task_id.startswith("mission_"):
            return [
                project_task_event(
                    event.to_dict(),
                    task_id=task_id,
                    kind="mission",
                )
                for event in self.store.mission_events_since(task_id)
            ]
        run = self._require_run(task_id)
        return [
            project_task_event(
                event.to_dict(),
                task_id=task_id,
                kind="run",
                adapter=run.spec.adapter,
            )
            for event in self.store.events_since(task_id)
        ]

    def task_artifacts(
        self,
        task_id: str,
        access_context: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        if self.get_task(task_id, access_context=access_context) is None:
            raise KeyError(task_id)
        if task_id.startswith("mission_"):
            return self.store.list_mission_artifacts(task_id)
        self._require_run(task_id)
        return self.store.list_artifacts(task_id)

    def task_result(
        self,
        task_id: str,
        access_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        task = self.get_task(task_id, access_context=access_context)
        if task is None:
            raise KeyError(task_id)
        artifacts = self.task_artifacts(task_id, access_context=access_context)
        events = self.task_events(task_id, access_context=access_context)
        summary = latest_task_summary(events)
        if not summary and artifacts:
            summary = "Artifacts are ready: " + ", ".join(
                artifact["name"] for artifact in artifacts[:5] if artifact.get("name")
            )
        return {
            "task_id": task_id,
            "status": task["status"],
            "summary": summary,
            "artifacts": artifacts,
            "completed": task["status"] in {"completed", "failed", "cancelled"},
            "generated_at": utc_timestamp(),
        }

    def send_input(self, run_id: str, prompt: str) -> None:
        run = self._require_run(run_id)
        if run.status != "running":
            self.store.append_event(
                run_id,
                "input.rejected",
                {"reason": f"run is {run.status}; input requires running"},
            )
            return
        self._adapter(run.spec.adapter).send_input(run, prompt, self.store)

    def cancel(self, run_id: str, reason: str | None = None) -> None:
        run = self._require_run(run_id)
        if self.store.is_terminal(run_id):
            self.store.append_event(run_id, "cancel.ignored", {"reason": "run already terminal"})
            return
        if self.store.cancel_job(run_id):
            self.store.append_event(
                run_id,
                "run.cancelled",
                {"reason": reason or "cancelled before worker claim"},
            )
            self._drain_queue()
            return
        job = self.store.get_job(run_id)
        if job and job.status == "running" and job.worker_id != self.worker_id:
            self.store.append_event(
                run_id,
                "run.cancel_requested",
                {
                    "worker_id": job.worker_id,
                    "reason": reason or "cancelled from control plane",
                },
            )
            return
        self._adapter(run.spec.adapter).cancel(run, reason, self.store)

    def resolve_permission(self, run_id: str, permission_id: str, payload: dict[str, Any]) -> None:
        run = self._require_run(run_id)
        decision = payload.get("decision")
        if decision not in {"approve", "deny", "cancel"}:
            raise ValueError("decision must be approve, deny, or cancel")
        job = self.store.get_job(run_id)
        if job and job.status == "running" and job.worker_id != self.worker_id:
            self.store.append_event(
                run_id,
                "permission.resolve_requested",
                {
                    "worker_id": job.worker_id,
                    "permission_id": permission_id,
                    "payload": payload,
                },
            )
            return
        self._adapter(run.spec.adapter).resolve_permission(run, permission_id, payload, self.store)

    def get_run(self, run_id: str) -> RunState | None:
        return self.store.get_run(run_id)

    def queue_status(self) -> dict[str, Any]:
        return self.store.queue_snapshot()

    def remote_worker_heartbeat(self, worker_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        worker_id = normalize_worker_id(worker_id)
        capacity = payload_positive_int(payload, "capacity", default=1)
        lease_ttl_seconds = payload_positive_int(
            payload,
            "lease_ttl_seconds",
            default=self.lease_ttl_seconds,
        )
        worker = self.store.heartbeat_worker(
            worker_id,
            capacity,
            lease_ttl_seconds,
            metadata=worker_metadata(payload, default_kind="remote"),
        )
        self.store.recover_expired_leases()
        return {
            **worker.to_dict(),
            "control": self.remote_worker_control(worker_id),
        }

    def claim_remote_run(self, worker_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        worker_id = normalize_worker_id(worker_id)
        capacity = payload_positive_int(payload, "capacity", default=1)
        lease_ttl_seconds = payload_positive_int(
            payload,
            "lease_ttl_seconds",
            default=self.lease_ttl_seconds,
        )
        worker = self.store.heartbeat_worker(
            worker_id,
            capacity,
            lease_ttl_seconds,
            metadata=worker_metadata(payload, default_kind="remote"),
        )
        self.store.recover_expired_leases()
        if worker.status == "draining":
            return {
                "worker": worker.to_dict(),
                "job": None,
                "run": None,
                "control": self.remote_worker_control(worker_id),
            }
        if self.store.active_job_count(worker_id) >= capacity:
            return {
                "worker": worker.to_dict(),
                "job": None,
                "run": None,
                "control": self.remote_worker_control(worker_id),
            }
        job = self.store.claim_next_job(
            worker_id,
            lease_ttl_seconds,
            predicate=lambda run: worker_matches_run(worker.metadata, run),
        )
        run = self.store.get_run(job.run_id) if job else None
        return {
            "worker": self.store.heartbeat_worker(
                worker_id,
                capacity,
                lease_ttl_seconds,
                metadata=worker.metadata,
            ).to_dict(),
            "job": job.to_dict() if job else None,
            "run": run.to_dict() if run else None,
            "control": self.remote_worker_control(worker_id),
        }

    def remote_worker_control(self, worker_id: str) -> dict[str, Any]:
        worker_id = normalize_worker_id(worker_id)
        worker = next(
            (
                item
                for item in self.store.queue_snapshot()["workers"]
                if item["worker_id"] == worker_id
            ),
            None,
        )
        running_jobs = self.store.running_jobs_for_worker(worker_id)
        runs: list[dict[str, Any]] = []
        for job in running_jobs:
            run = self.store.get_run(job.run_id)
            if run is None or run.status in {"completed", "failed", "cancelled"}:
                continue
            events = self.store.events_since(job.run_id)
            cancel_event = latest_event(events, "run.cancel_requested")
            permission_requests = [
                event
                for event in events
                if event.type == "permission.resolve_requested"
                and event.data.get("worker_id") == worker_id
            ]
            runs.append(
                {
                    "run_id": job.run_id,
                    "cancel": cancel_event.to_dict() if cancel_event else None,
                    "permission_resolutions": [
                        event.to_dict()
                        for event in permission_requests
                        if not permission_resolution_applied(events, event)
                    ],
                }
            )
        desired_state = (
            str((worker or {}).get("metadata", {}).get("desired_state") or "").lower()
            if worker
            else ""
        )
        draining = bool(
            worker
            and (
                worker.get("status") == "draining"
                or desired_state == "draining"
            )
        )
        return {
            "worker_id": worker_id,
            "draining": draining,
            "desired_state": "draining" if draining else "active",
            "runs": runs,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        }

    def drain_worker(self, worker_id: str, reason: str | None = None) -> dict[str, Any]:
        worker_id = normalize_worker_id(worker_id)
        worker = self.store.set_worker_state(
            worker_id,
            "draining",
            {
                "desired_state": "draining",
                "drain_reason": reason or "drain requested from control plane",
                "drain_requested_at": datetime.now(timezone.utc).isoformat(
                    timespec="milliseconds"
                ),
            },
        )
        return {"worker": worker.to_dict(), "control": self.remote_worker_control(worker_id)}

    def resume_worker(self, worker_id: str) -> dict[str, Any]:
        worker_id = normalize_worker_id(worker_id)
        worker = self.store.set_worker_state(
            worker_id,
            "active",
            {"desired_state": "active", "resume_requested_at": utc_timestamp()},
        )
        self._drain_queue()
        return {"worker": worker.to_dict(), "control": self.remote_worker_control(worker_id)}

    def retry_worker_runs(self, worker_id: str, reason: str | None = None) -> dict[str, Any]:
        worker_id = normalize_worker_id(worker_id)
        run_ids = self.store.requeue_running_jobs_for_worker(
            worker_id,
            reason or "retry requested from control plane",
        )
        self._drain_queue()
        return {
            "worker_id": worker_id,
            "requeued_run_ids": run_ids,
            "control": self.remote_worker_control(worker_id),
        }

    def create_worker_registration(self, payload: dict[str, Any]) -> dict[str, Any]:
        worker_id = normalize_worker_id(str(payload.get("worker_id") or "worker-vps"))
        control_url = str(payload.get("control_url") or "").strip()
        if not control_url:
            raise ValueError("control_url is required")
        capacity = payload_positive_int(payload, "capacity", default=1)
        labels = payload.get("labels") if isinstance(payload.get("labels"), dict) else {}
        resources = payload.get("resources") if isinstance(payload.get("resources"), dict) else {}
        metadata = {
            "worker_id": worker_id,
            "kind": "remote",
            "labels": labels,
            "resources": resources,
            "desired_state": "active",
        }
        token = self.access.create_token(
            {
                "name": f"worker-{worker_id}",
                "project_id": payload.get("project_id") or "default",
                "scopes": ["workers:*"],
                "metadata": metadata,
            }
        )
        worker_metadata = {
            "labels": labels,
            "resources": resources,
            "capabilities": {
                "features": ["artifacts", "claim", "events", "heartbeat", "control"],
            },
        }
        deploy_command = worker_deploy_command(
            control_url=control_url,
            token=str(token["token"]),
            worker_id=worker_id,
            capacity=capacity,
            metadata=worker_metadata,
        )
        return {
            "worker_id": worker_id,
            "capacity": capacity,
            "control_url": control_url,
            "token": token,
            "metadata": worker_metadata,
            "deploy_command": deploy_command,
        }

    def append_remote_worker_event(
        self,
        worker_id: str,
        run_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        worker_id = normalize_worker_id(worker_id)
        self._require_worker_job(worker_id, run_id)
        event_type = payload.get("type") or payload.get("event_type")
        if not isinstance(event_type, str) or not event_type.strip():
            raise ValueError("event type is required")
        raw_data = payload.get("data", {})
        if raw_data is None:
            raw_data = {}
        if not isinstance(raw_data, dict):
            raise ValueError("event data must be an object")
        data = dict(raw_data)
        data.setdefault("worker_id", worker_id)
        event = self.store.append_event(run_id, event_type.strip(), data)
        return event.to_dict()

    def write_remote_worker_artifact(
        self,
        worker_id: str,
        run_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        worker_id = normalize_worker_id(worker_id)
        self._require_worker_job(worker_id, run_id)
        name = payload.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("artifact name is required")
        mode = str(payload.get("mode") or "write").strip().lower()
        if mode not in {"write", "append"}:
            raise ValueError("artifact mode must be write or append")
        if "json" in payload:
            if mode == "append":
                raise ValueError("json artifacts cannot use append mode")
            content = json.dumps(payload["json"], ensure_ascii=False, indent=2)
        else:
            content = payload.get("content")
            if not isinstance(content, str):
                raise ValueError("artifact content or json is required")
        if len(content.encode("utf-8")) > MAX_REMOTE_ARTIFACT_BYTES:
            raise ValueError("artifact content exceeds remote upload limit")
        path = (
            self.store.append_text(run_id, name.strip(), content)
            if mode == "append"
            else self.store.write_text(run_id, name.strip(), content)
        )
        event = self.store.append_event(
            run_id,
            "artifact.uploaded",
            {
                "worker_id": worker_id,
                "name": path.name,
                "size_bytes": path.stat().st_size,
                "mode": mode,
                "chunk_index": payload.get("chunk_index"),
                "final": bool(payload.get("final")),
            },
        )
        return {"artifact": {"name": path.name}, "event": event.to_dict()}

    def executors(self) -> dict[str, Any]:
        return self.executor_registry.snapshot()

    def cleanup_once(self) -> dict[str, Any]:
        return self.cleanup_manager.run_once().to_dict()

    def metrics(self) -> dict[str, Any]:
        metrics = self.ops.metrics()
        metrics["cost"] = self.cost.summary()
        return metrics

    def operations_status(self) -> dict[str, Any]:
        status = self.ops.status()
        status["cost"] = self.cost.summary()
        return status

    def cost_status(self) -> dict[str, Any]:
        return self.cost.status()

    def p5_evaluations(self) -> dict[str, Any]:
        return self.ops.p5_evaluations()

    def run_drills(self) -> dict[str, Any]:
        return self.ops.run_drills()

    def create_backup(self) -> dict[str, Any]:
        return self.ops.create_backup()

    def list_backups(self) -> list[dict[str, Any]]:
        return self.ops.list_backups()

    def backup_path(self, name: str) -> Path:
        return self.ops.backup_path(name)

    def access_policy(
        self,
        headers: Any | None = None,
        principal: str | None = None,
        roles: list[str] | None = None,
    ) -> dict[str, Any]:
        policy = self.access.policy(headers, principal=principal)
        if roles is not None:
            policy["current_principal"]["roles"] = roles
        return policy

    def create_access_project(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.access.create_project(payload)

    def list_access_projects(self) -> dict[str, Any]:
        return self.access.list_projects()

    def create_api_token(
        self,
        payload: dict[str, Any],
        headers: Any | None = None,
        principal: str | None = None,
    ) -> dict[str, Any]:
        return self.access.create_token(payload, headers=headers, principal=principal)

    def list_api_tokens(self) -> dict[str, Any]:
        return self.access.list_tokens()

    def revoke_api_token(self, token_id: str) -> dict[str, Any]:
        return self.access.revoke_token(token_id)

    def run_audit_bundle(self, run_id: str) -> dict[str, Any]:
        run = self._require_run(run_id)
        executor = self.store.get_executor_lease_for_run(run_id)
        return {
            "run": run.to_dict(),
            "events": [event.to_dict() for event in self.store.events_since(run_id)],
            "raw_events": self.store.raw_events(run_id),
            "ui_daemon_events": project_events(
                self.store.events_since(run_id),
                source_adapter=run.spec.adapter,
            ),
            "permission_notifications": [
                notification.to_dict()
                for notification in self.store.list_permission_notifications(run_id=run_id)
            ],
            "artifacts": self.store.list_artifacts(run_id),
            "queue": self.queue_status(),
            "executor": executor.to_dict() if executor else None,
            "cost": self.cost.run_cost_entry(run),
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        }

    def list_profiles(self) -> list[dict[str, Any]]:
        return [profile.to_dict() for profile in self.store.list_profiles()]

    def get_profile(self, profile_id: str) -> dict[str, Any] | None:
        profile = self.store.get_profile(profile_id)
        return profile.to_dict() if profile else None

    def list_permission_notifications(
        self,
        run_id: str | None = None,
        permission_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if run_id is not None:
            self._require_run(run_id)
        return [
            notification.to_dict()
            for notification in self.store.list_permission_notifications(
                run_id=run_id,
                permission_id=permission_id,
            )
        ]

    def retry_permission_notifications(
        self,
        run_id: str,
        permission_id: str,
    ) -> list[dict[str, Any]]:
        run = self._require_run(run_id)
        request_event = latest_permission_request(
            self.store.events_since(run_id),
            permission_id,
        )
        if request_event is None:
            raise ValueError("permission request not found")
        notifications = self.store.list_permission_notifications(
            run_id=run_id,
            permission_id=permission_id,
        )
        if not notifications:
            self._notify_permission_request(request_event)
            notifications = self.store.list_permission_notifications(
                run_id=run_id,
                permission_id=permission_id,
            )
        for notification in notifications:
            if notification.status == "sent":
                continue
            self._deliver_permission_notification(notification, run, request_event)
        return [
            notification.to_dict()
            for notification in self.store.list_permission_notifications(
                run_id=run_id,
                permission_id=permission_id,
            )
        ]

    def create_profile(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.missions.create_profile(payload).to_dict()

    def create_mission(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.missions.create_mission(payload)

    def list_missions(self) -> list[dict[str, Any]]:
        missions = sorted(
            self.store.list_missions(),
            key=lambda mission: mission.created_at,
            reverse=True,
        )
        return [self.store.mission_snapshot(mission.mission_id) for mission in missions]

    def get_mission(self, mission_id: str) -> dict[str, Any] | None:
        return self.missions.get_mission(mission_id)

    def cancel_mission(self, mission_id: str, reason: str | None = None) -> dict[str, Any]:
        return self.missions.cancel_mission(mission_id, reason)

    def override_review_gate(
        self,
        mission_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return self.missions.override_review_gate(mission_id, payload)

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._stop.set()
        if self._heartbeat_thread:
            self._heartbeat_thread.join(timeout=2)
        if self._cleanup_thread:
            self._cleanup_thread.join(timeout=2)
        with self._run_threads_lock:
            run_threads = list(self._run_threads)
        for thread in run_threads:
            thread.join(timeout=2)
        for adapter in self.adapters.values():
            adapter.shutdown()
        self.executor_registry.shutdown()
        self.v2.close()
        self.store.close()

    def _require_run(self, run_id: str) -> RunState:
        run = self.store.get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        return run

    def _task_from_run(self, run: RunState) -> dict[str, Any]:
        events = self.store.events_since(run.run_id)
        permission_count = pending_permission_count(events)
        metadata = dict(run.spec.metadata or {})
        title = str(metadata.get("task_title") or first_line(run.spec.prompt) or run.run_id)
        result_summary = latest_run_summary(events)
        return {
            "task_id": run.run_id,
            "kind": "run",
            "title": title,
            "goal": run.spec.prompt or title,
            "status": task_status(run.status),
            "created_at": run.created_at,
            "updated_at": run.updated_at,
            "progress": {
                "completed_steps": 1 if run.status in {"completed", "failed", "cancelled"} else 0,
                "total_steps": 1,
                "percent": task_progress_percent(run.status),
            },
            "agent_summary": {
                "adapter": run.spec.adapter,
                "model": run.spec.model,
                "active_agent": adapter_display_name(run.spec.adapter),
            },
            "needs_attention": permission_count > 0,
            "pending_permission_count": permission_count,
            "access": task_access_from_metadata(metadata),
            "source": {"run_id": run.run_id, "mission_id": None},
            "result_summary": result_summary,
            "links": {
                "detail": f"/tasks/{run.run_id}",
                "source": f"/runs/{run.run_id}",
                "audit": f"/runs/{run.run_id}/audit.json",
            },
        }

    def _task_from_mission_snapshot(self, mission: dict[str, Any]) -> dict[str, Any]:
        task_count = int(mission.get("task_count") or len(mission.get("tasks") or []))
        completed = int(mission.get("completed_task_count") or 0)
        status = str(mission.get("status") or "created")
        spec = mission.get("spec") if isinstance(mission.get("spec"), dict) else {}
        tasks = mission.get("tasks") if isinstance(mission.get("tasks"), list) else []
        active_task = next(
            (
                task
                for task in tasks
                if isinstance(task, dict)
                and task.get("status") not in {"completed", "failed", "cancelled"}
            ),
            None,
        )
        return {
            "task_id": mission["mission_id"],
            "kind": "mission",
            "title": first_line(str(spec.get("goal") or mission["mission_id"])),
            "goal": spec.get("goal") or mission["mission_id"],
            "status": task_status(status),
            "created_at": mission["created_at"],
            "updated_at": mission["updated_at"],
            "progress": {
                "completed_steps": completed,
                "total_steps": max(task_count, 1),
                "percent": int((completed / max(task_count, 1)) * 100),
            },
            "agent_summary": {
                "adapter": spec.get("adapter"),
                "strategy": spec.get("strategy"),
                "active_agent": (
                    active_task.get("profile_id") if isinstance(active_task, dict) else None
                ),
            },
            "needs_attention": status in {"review_blocked", "blocked"},
            "pending_permission_count": 0,
            "access": task_access_from_metadata(spec.get("metadata")),
            "source": {"run_id": None, "mission_id": mission["mission_id"]},
            "result_summary": mission_result_summary(mission),
            "links": {
                "detail": f"/tasks/{mission['mission_id']}",
                "source": f"/missions/{mission['mission_id']}",
            },
        }

    def _require_worker_job(self, worker_id: str, run_id: str) -> None:
        job = self.store.get_job(run_id)
        if job is None:
            raise KeyError(run_id)
        if job.worker_id != worker_id:
            raise ValueError("run is not leased to this worker")
        if job.status != "running":
            raise ValueError(f"run lease is {job.status}")

    def _adapter(self, name: str) -> RuntimeAdapter:
        adapter = self.adapters.get(name)
        if adapter is None:
            raise ValueError(f"unknown adapter: {name}")
        return adapter

    def _drain_queue(self) -> None:
        if self.worker_capacity <= 0:
            return
        with self._scheduler_lock:
            self.store.heartbeat_worker(
                self.worker_id,
                self.worker_capacity,
                self.lease_ttl_seconds,
            )
            self.store.recover_expired_leases()
            while self.store.active_job_count(self.worker_id) < self.worker_capacity:
                job = self.store.claim_next_job(self.worker_id, self.lease_ttl_seconds)
                if job is None:
                    return
                thread = threading.Thread(
                    target=self._start_claimed_run,
                    args=(job.run_id,),
                    name=f"runtime-run-{job.run_id}",
                    daemon=True,
                )
                with self._run_threads_lock:
                    self._run_threads.append(thread)
                thread.start()

    def _start_claimed_run(self, run_id: str) -> None:
        run = self._require_run(run_id)
        if self.store.is_terminal(run_id):
            return
        self._start_timeout_watchdog(run_id, run.spec.timeout_seconds)
        adapter = self._adapter(run.spec.adapter)
        adapter.start(run, self.store)
        current = self._require_run(run_id)
        if current.spec.prompt and not self.store.is_terminal(run_id):
            adapter.send_input(current, current.spec.prompt, self.store)

    def _start_timeout_watchdog(self, run_id: str, timeout_seconds: int | None) -> None:
        if not timeout_seconds or timeout_seconds <= 0:
            return
        thread = threading.Thread(
            target=self._timeout_watchdog,
            args=(run_id, timeout_seconds),
            name=f"runtime-timeout-{run_id}",
            daemon=True,
        )
        thread.start()

    def _timeout_watchdog(self, run_id: str, timeout_seconds: int) -> None:
        deadline = time.monotonic() + timeout_seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            if self._stop.wait(min(1.0, remaining)):
                return
            if self.store.is_terminal(run_id):
                return
        run = self.store.get_run(run_id)
        if run is None:
            return
        self.store.append_event(
            run_id,
            "resources.timeout",
            {"timeout_seconds": timeout_seconds},
        )
        self._adapter(run.spec.adapter).cancel(
            run,
            f"resource timeout after {timeout_seconds}s",
            self.store,
        )

    def _heartbeat_loop(self) -> None:
        interval = max(1.0, min(5.0, self.lease_ttl_seconds / 3))
        while not self._stop.wait(interval):
            try:
                self.store.heartbeat_worker(
                    self.worker_id,
                    self.worker_capacity,
                    self.lease_ttl_seconds,
                )
                self.store.recover_expired_leases()
                self._drain_queue()
            except Exception:
                return

    def _cleanup_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.cleanup_once()
            except Exception:
                pass
            if self._stop.wait(self.cleanup_manager.policy.interval_seconds):
                return

    def _on_event(self, event: RuntimeEvent) -> None:
        self.missions.handle_run_event(event)
        if event.type == "permission.requested":
            self._notify_permission_request(event)
            self._start_permission_watchdog(event)
        if event.type in TERMINAL_RUN_EVENTS:
            self._drain_queue()
            run = self.store.get_run(event.run_id)
            metadata = run.spec.metadata if run else {}
            mission_id = metadata.get("mission_id")
            if isinstance(mission_id, str):
                self.missions.drain_mission(mission_id)

    def _notify_permission_request(self, event: RuntimeEvent) -> None:
        permission_id = permission_id_from_event(event)
        run = self.store.get_run(event.run_id)
        if not permission_id or run is None:
            return
        existing = self.store.list_permission_notifications(
            run_id=event.run_id,
            permission_id=permission_id,
        )
        if any(
            notification.metadata.get("event_id") == event.id
            for notification in existing
        ):
            return
        for notification in self.permission_notifier.notifications_for(
            run=run,
            permission_id=permission_id,
            event=event,
        ):
            self.store.create_permission_notification(notification)
            self.store.append_event(
                event.run_id,
                "permission.notification.queued",
                notification_event_data(notification),
            )
            self._deliver_permission_notification(notification, run, event)

    def _deliver_permission_notification(
        self,
        notification: Any,
        run: RunState,
        event: RuntimeEvent,
    ) -> None:
        result = self.permission_notifier.deliver(notification, run=run, event=event)
        now = utc_timestamp()
        notification.attempts += 1
        notification.status = result.status
        notification.delivery_ref = result.delivery_ref
        notification.error = result.error
        notification.updated_at = now
        if result.status == "sent":
            notification.sent_at = now
        self.store.update_permission_notification(notification)
        self.store.append_event(
            notification.run_id,
            f"permission.notification.{result.status}",
            {
                **notification_event_data(notification),
                "delivery_ref": notification.delivery_ref,
                "error": notification.error,
                "attempts": notification.attempts,
            },
        )

    def _start_permission_watchdog(self, event: RuntimeEvent) -> None:
        permission_id = permission_id_from_event(event)
        if not permission_id or self.permission_stall_seconds <= 0:
            return
        thread = threading.Thread(
            target=self._permission_watchdog,
            args=(event.run_id, event.sequence, permission_id),
            name=f"runtime-permission-{event.run_id}-{event.sequence}",
            daemon=True,
        )
        thread.start()

    def _permission_watchdog(
        self,
        run_id: str,
        requested_sequence: int,
        permission_id: str,
    ) -> None:
        if self._stop.wait(self.permission_stall_seconds):
            return
        if self.store.is_terminal(run_id) or self._permission_is_resolved(
            run_id,
            permission_id,
            requested_sequence,
        ):
            return
        self.store.append_event(
            run_id,
            "permission.stalled",
            {
                "permission_id": permission_id,
                "requested_sequence": requested_sequence,
                "stall_seconds": self.permission_stall_seconds,
                "action": self.permission_stall_action,
            },
        )
        if self.permission_stall_action == "cancel":
            self.cancel(run_id, f"permission stalled after {self.permission_stall_seconds}s")
        elif self.permission_stall_action == "deny":
            try:
                self.resolve_permission(
                    run_id,
                    permission_id,
                    {
                        "decision": "deny",
                        "option_id": "cancel",
                        "decided_by": "permission-watchdog",
                        "reason": (
                            "permission stalled after "
                            f"{self.permission_stall_seconds}s"
                        ),
                    },
                )
            except Exception as exc:  # noqa: BLE001 - audit failed recovery action
                self.store.append_event(
                    run_id,
                    "permission.stall_recovery_failed",
                    {"permission_id": permission_id, "reason": str(exc)},
                )

    def _permission_is_resolved(
        self,
        run_id: str,
        permission_id: str,
        requested_sequence: int,
    ) -> bool:
        for event in self.store.events_since(run_id, requested_sequence):
            if event.type != "permission.resolved":
                continue
            if permission_id_from_event(event) == permission_id:
                return True
        return False


def positive_int(value: int | None, env_value: str | None, default: int) -> int:
    candidate: int | None = value
    if candidate is None and env_value:
        try:
            candidate = int(env_value)
        except ValueError:
            candidate = None
    if candidate is None:
        candidate = default
    return max(0, candidate)


def payload_positive_int(payload: dict[str, Any], key: str, default: int) -> int:
    value = payload.get(key)
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, str):
        try:
            return max(0, int(value))
        except ValueError:
            return default
    return default


def normalize_worker_id(value: str) -> str:
    worker_id = value.strip()
    if not worker_id:
        raise ValueError("worker id is required")
    return worker_id


def worker_metadata(payload: dict[str, Any], *, default_kind: str) -> dict[str, Any]:
    raw_metadata = payload.get("metadata")
    metadata = dict(raw_metadata) if isinstance(raw_metadata, dict) else {}
    kind = payload.get("kind")
    metadata["kind"] = kind if isinstance(kind, str) and kind else default_kind
    for key in ("endpoint", "hostname", "version", "region", "zone"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            metadata[key] = value
    for key in ("labels", "capabilities", "resources", "executor", "sandbox"):
        value = payload.get(key)
        if isinstance(value, (dict, list)):
            metadata[key] = value
    return metadata


def worker_matches_run(worker: dict[str, Any], run: RunState) -> bool:
    requirements = worker_requirements(run)
    capabilities = dict_value(worker.get("capabilities"))
    adapters = string_set(capabilities.get("adapters"))
    required_adapters = string_set(requirements.get("adapters")) or {run.spec.adapter}
    if adapters and required_adapters and adapters.isdisjoint(required_adapters):
        return False
    if not contains_all(
        string_set(capabilities.get("features")),
        string_set(requirements.get("features")),
    ):
        return False
    if not mapping_contains(worker_labels(worker), dict_value(requirements.get("labels"))):
        return False
    if not resources_satisfy(
        dict_value(worker.get("resources")),
        dict_value(requirements.get("resources")),
    ):
        return False
    for key in ("executor", "sandbox"):
        if not mapping_contains(dict_value(worker.get(key)), dict_value(requirements.get(key))):
            return False
    return True


def worker_requirements(run: RunState) -> dict[str, Any]:
    metadata = run.spec.metadata if isinstance(run.spec.metadata, dict) else {}
    raw = metadata.get("worker_requirements") or metadata.get("required_worker")
    return dict(raw) if isinstance(raw, dict) else {}


def worker_labels(worker: dict[str, Any]) -> dict[str, Any]:
    labels = dict_value(worker.get("labels"))
    for key in ("region", "zone"):
        if key in worker and key not in labels:
            labels[key] = worker[key]
    return labels


def dict_value(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def string_set(value: Any) -> set[str]:
    if isinstance(value, str):
        return {value}
    if isinstance(value, list):
        return {item for item in value if isinstance(item, str) and item}
    return set()


def contains_all(actual: set[str], required: set[str]) -> bool:
    return not required or required.issubset(actual)


def mapping_contains(actual: dict[str, Any], required: dict[str, Any]) -> bool:
    for key, value in required.items():
        if actual.get(key) != value:
            return False
    return True


def resources_satisfy(actual: dict[str, Any], required: dict[str, Any]) -> bool:
    for key, required_value in required.items():
        actual_value = actual.get(key)
        if isinstance(required_value, (int, float)) and isinstance(actual_value, (int, float)):
            if actual_value < required_value:
                return False
            continue
        if actual_value != required_value:
            return False
    return True


def normalize_permission_stall_action(value: str | None) -> str:
    action = (value or "audit").strip().lower()
    if action not in {"audit", "deny", "cancel"}:
        return "audit"
    return action


def permission_id_from_event(event: RuntimeEvent) -> str | None:
    data = event.data or {}
    permission_id = data.get("permission_id")
    if isinstance(permission_id, str) and permission_id:
        return permission_id
    raw = data.get("raw")
    if isinstance(raw, dict):
        raw_data = raw.get("data")
        if isinstance(raw_data, dict):
            request_id = raw_data.get("requestId") or raw_data.get("permission_id")
            if isinstance(request_id, str) and request_id:
                return request_id
    return None


def pending_permission_count(events: list[RuntimeEvent]) -> int:
    requested: set[str] = set()
    resolved: set[str] = set()
    for event in events:
        permission_id = permission_id_from_event(event)
        if not permission_id:
            continue
        if event.type == "permission.requested":
            requested.add(permission_id)
        elif event.type in {"permission.resolved", "permission.resolve_failed"}:
            resolved.add(permission_id)
    return len(requested - resolved)


def first_line(value: Any, *, limit: int = 96) -> str:
    text = str(value or "").strip().splitlines()[0].strip() if value else ""
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3]}..."


def adapter_display_name(adapter: str) -> str:
    return {"fake": "Smoke Test Agent", "qwen": "Qwen Agent"}.get(adapter, adapter)


def task_status(status: str) -> str:
    if status in {"created", "pending", "waiting_dependencies"}:
        return "queued"
    if status in {"review_blocked", "blocked"}:
        return "blocked"
    return status


def task_progress_percent(status: str) -> int:
    if status == "completed":
        return 100
    if status in {"failed", "cancelled"}:
        return 100
    if status == "running":
        return 50
    if status == "queued":
        return 10
    return 0


def latest_run_summary(events: list[RuntimeEvent]) -> str | None:
    for event in reversed(events):
        if event.type in {"run.completed", "run.failed", "adapter.completed"}:
            text = event_text(event.data)
            if text:
                return first_line(text, limit=220)
        if event.type == "message.delta":
            text = event_text(event.data)
            if text:
                return first_line(text, limit=220)
    return None


def latest_task_summary(events: list[dict[str, Any]]) -> str | None:
    for event in reversed(events):
        body = event.get("body")
        if isinstance(body, str) and body.strip():
            if event.get("status") in {"completed", "failed"} or event.get("type") in {
                "agent.message",
                "task.completed",
                "task.failed",
            }:
                return first_line(body, limit=220)
    return None


def mission_result_summary(mission: dict[str, Any]) -> str | None:
    tasks = mission.get("tasks")
    if not isinstance(tasks, list):
        return None
    completed: list[str] = []
    for task in tasks:
        if not isinstance(task, dict) or task.get("status") != "completed":
            continue
        title = task.get("title")
        if isinstance(title, str) and title:
            completed.append(title)
    if not completed:
        return None
    return "Completed: " + ", ".join(completed[:5])


def project_task_event(
    event: dict[str, Any],
    *,
    task_id: str,
    kind: str,
    adapter: str | None = None,
) -> dict[str, Any]:
    event_type = str(event.get("type") or "event")
    title, status = task_event_title_status(event_type, kind=kind)
    body = event_text(dict_value(event.get("data")))
    return {
        "id": event.get("id") or f"{task_id}:{event.get('sequence')}",
        "task_id": task_id,
        "sequence": event.get("sequence") or 0,
        "type": task_event_type(event_type),
        "title": title,
        "body": body,
        "status": status,
        "created_at": event.get("created_at"),
        "source_event_type": event_type,
        "source": {
            "kind": kind,
            "adapter": adapter,
            "raw": event,
        },
    }


def task_event_type(event_type: str) -> str:
    mapping = {
        "run.created": "task.accepted",
        "run.queued": "task.queued",
        "run.started": "agent.started",
        "workspace.prepared": "environment.prepared",
        "resources.resolved": "environment.prepared",
        "cost.quoted": "task.planned",
        "executor.acquired": "agent.started",
        "executor.starting": "agent.started",
        "lease.claimed": "agent.started",
        "input.accepted": "user.message",
        "message.delta": "agent.message",
        "step.started": "agent.progress",
        "tool.completed": "agent.progress",
        "permission.requested": "permission.required",
        "permission.resolved": "permission.resolved",
        "run.completed": "task.completed",
        "run.failed": "task.failed",
        "run.cancelled": "task.cancelled",
        "mission.created": "task.accepted",
        "mission.started": "agent.started",
        "mission.completed": "task.completed",
        "mission.failed": "task.failed",
        "mission.cancelled": "task.cancelled",
        "task.created": "agent.assigned",
        "task.started": "agent.started",
        "task.completed": "agent.completed",
        "task.failed": "agent.failed",
    }
    return mapping.get(event_type, "agent.progress")


def task_event_title_status(event_type: str, *, kind: str) -> tuple[str, str]:
    event_type_name = task_event_type(event_type)
    if event_type_name == "task.accepted":
        return ("Task accepted", "queued")
    if event_type_name == "task.queued":
        return ("Waiting for an execution unit", "queued")
    if event_type_name == "environment.prepared":
        return ("Environment prepared", "running")
    if event_type_name == "task.planned":
        return ("Plan and budget checked", "running")
    if event_type_name == "agent.assigned":
        return ("Agent assigned", "running")
    if event_type_name == "agent.started":
        return ("Agent started", "running")
    if event_type_name == "user.message":
        return ("User message received", "running")
    if event_type_name == "agent.message":
        return ("Agent update", "running")
    if event_type_name == "permission.required":
        return ("Action needs approval", "blocked")
    if event_type_name == "permission.resolved":
        return ("Approval resolved", "running")
    if event_type_name == "task.completed":
        return ("Task completed", "completed")
    if event_type_name == "task.failed":
        return ("Task failed", "failed")
    if event_type_name == "task.cancelled":
        return ("Task cancelled", "cancelled")
    if event_type_name == "agent.completed":
        return ("Agent finished a step", "completed")
    if event_type_name == "agent.failed":
        return ("Agent step failed", "failed")
    return ("Mission event" if kind == "mission" else "Agent progress", "running")


def event_text(data: dict[str, Any]) -> str | None:
    for key in ("summary", "text", "message", "output", "prompt", "prompt_preview", "reason"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    raw = dict_value(data.get("raw"))
    raw_data = dict_value(raw.get("data"))
    update = dict_value(raw_data.get("update")) or raw_data
    content = dict_value(update.get("content"))
    text = content.get("text") or update.get("rawOutput")
    if isinstance(text, str) and text.strip():
        return text.strip()
    tool_call = dict_value(raw_data.get("toolCall")) or dict_value(update.get("toolCall"))
    title = tool_call.get("title") or tool_call.get("name")
    if isinstance(title, str) and title.strip():
        return title.strip()
    task_title = data.get("task_title") or data.get("title")
    if isinstance(task_title, str) and task_title.strip():
        return task_title.strip()
    return None


def task_access_metadata(
    payload: dict[str, Any],
    access_context: dict[str, Any] | None,
) -> dict[str, Any]:
    metadata = dict_value(payload.get("metadata"))
    project_id = payload.get("project_id") or metadata.get("project_id")
    created_by = metadata.get("created_by")
    if access_context:
        created_by = access_context.get("principal_id") or created_by
        project_id = project_id or access_context.get("project_id")
    visibility = str(
        payload.get("visibility") or metadata.get("visibility") or "project"
    ).strip().lower()
    if visibility not in {"private", "project"}:
        visibility = "project"
    access: dict[str, Any] = {"visibility": visibility}
    if isinstance(created_by, str) and created_by.strip():
        access["created_by"] = created_by.strip()
    if isinstance(project_id, str) and project_id.strip():
        access["project_id"] = project_id.strip()
    elif access_context and access_context.get("principal_id"):
        access["project_id"] = "default"
    return access


def task_access_from_metadata(metadata: Any) -> dict[str, Any]:
    data = dict_value(metadata)
    visibility = str(data.get("visibility") or "project").strip().lower()
    if visibility not in {"private", "project"}:
        visibility = "project"
    access = {"visibility": visibility}
    created_by = data.get("created_by")
    project_id = data.get("project_id")
    if isinstance(created_by, str) and created_by.strip():
        access["created_by"] = created_by.strip()
    if isinstance(project_id, str) and project_id.strip():
        access["project_id"] = project_id.strip()
    return access


def task_access_allowed(
    task_access: Any,
    access_context: dict[str, Any] | None,
) -> bool:
    if not access_context:
        return True
    roles = access_context.get("roles")
    if isinstance(roles, list) and "owner" in roles:
        return True
    scopes = access_context.get("scopes")
    if isinstance(scopes, list) and any(scope in {"*", "*:*"} for scope in scopes):
        return True
    access = dict_value(task_access)
    created_by = access.get("created_by")
    principal_id = access_context.get("principal_id")
    if principal_id and created_by == principal_id:
        return True
    visibility = str(access.get("visibility") or "project")
    project_id = access.get("project_id")
    context_project_id = access_context.get("project_id")
    return bool(
        visibility == "project"
        and project_id
        and context_project_id
        and project_id == context_project_id
    )


def latest_permission_request(
    events: list[RuntimeEvent],
    permission_id: str,
) -> RuntimeEvent | None:
    matches = [
        event
        for event in events
        if event.type == "permission.requested"
        and permission_id_from_event(event) == permission_id
    ]
    return matches[-1] if matches else None


def notification_event_data(notification: Any) -> dict[str, Any]:
    return {
        "notification_id": notification.notification_id,
        "permission_id": notification.permission_id,
        "channel": notification.channel,
        "target": notification.target,
        "status": notification.status,
        "action_url": notification.action_url,
    }


def latest_event(events: list[RuntimeEvent], event_type: str) -> RuntimeEvent | None:
    matches = [event for event in events if event.type == event_type]
    return matches[-1] if matches else None


def permission_resolution_applied(
    events: list[RuntimeEvent],
    request_event: RuntimeEvent,
) -> bool:
    permission_id = request_event.data.get("permission_id")
    requested_sequence = request_event.sequence
    for event in events:
        if event.sequence <= requested_sequence:
            continue
        if event.type not in {"permission.resolved", "permission.resolve_failed"}:
            continue
        if event.data.get("permission_id") == permission_id:
            return True
    return False


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def shell_single_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def worker_deploy_command(
    *,
    control_url: str,
    token: str,
    worker_id: str,
    capacity: int,
    metadata: dict[str, Any],
) -> str:
    metadata_json = json.dumps(metadata, ensure_ascii=False, sort_keys=True)
    return " \\\n  ".join(
        [
            f"RUN_WORKER_CONTROL_URL={shell_single_quote(control_url)}",
            f"RUN_WORKER_TOKEN={shell_single_quote(token)}",
            f"RUN_WORKER_ID={shell_single_quote(worker_id)}",
            f"RUN_WORKER_CAPACITY={capacity}",
            f"RUN_WORKER_METADATA_JSON={shell_single_quote(metadata_json)}",
            "bash scripts/deploy_worker_vps.sh root@<worker-ip> /path/to/key.pem",
        ]
    )
