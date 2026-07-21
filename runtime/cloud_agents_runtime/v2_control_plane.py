from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
import shlex
import shutil
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib import request
from urllib.error import URLError
from uuid import uuid4

from .agent_events import validate_worker_event
from .database import RuntimeDatabase
from .events import utc_now


TERMINAL_TASK_STATUSES = {"completed", "failed", "cancelled"}
SUPPORTED_MODES = {"auto", "single", "workflow", "multi-agent"}
SUPPORTED_CHANNELS = {"web", "mobile", "dingtalk", "feishu", "wecom"}
SUPPORTED_ADAPTERS = {"auto", "fake", "qwen", "codex", "claude", "opencode"}
TASK_STATUS_TRANSITIONS = {
    "queued": {"running", "failed", "cancelled"},
    "running": {"completed", "failed", "cancelled"},
    # A post-run workflow/evaluation failure may invalidate a completed result.
    "completed": {"queued", "failed"},
    "failed": {"queued"},
    "cancelled": {"queued"},
}
AGENT_STATUS_TRANSITIONS = {
    "queued": {"running", "failed", "cancelled"},
    "running": {"queued", "completed", "failed", "cancelled"},
    "completed": {"queued"},
    "failed": {"queued"},
    "cancelled": {"queued"},
}


def local_execution_unit_json(name: str, default: dict[str, Any]) -> dict[str, Any]:
    raw = os.environ.get(name)
    if not raw:
        return dict(default)
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{name} must contain a JSON object") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{name} must contain a JSON object")
    return value


def comma_list_env(name: str, default: list[str]) -> list[str]:
    raw = os.environ.get(name)
    if raw is None:
        return list(default)
    values = list(dict.fromkeys(item.strip() for item in raw.split(",") if item.strip()))
    if not values:
        raise ValueError(f"{name} must contain at least one value")
    return values


class V2ControlPlane:
    """V2 modular-monolith control plane slice.

    This intentionally does not reuse v1 run/mission tables. It provides the
    Task-first domain model described by the V2 roadmap while staying lightweight
    enough for local product iteration.
    """

    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "control_plane.db"
        database_url = os.environ.get("V2_DATABASE_URL") or os.environ.get("DATABASE_URL")
        self._db = RuntimeDatabase(self.db_path, database_url)
        self._lock = threading.RLock()
        self._threads: dict[str, threading.Thread] = {}
        self._closed = False
        self._db_closed = False
        self._db.task_lock("agentflow-v2-schema")
        self._init_db()
        self._ensure_defaults()
        self._recover_open_tasks()

    def capabilities(self) -> dict[str, Any]:
        return {
            "version": "v2-control-plane-slice",
            "status": "usable-mvp",
            "features": [
                "task_first_api",
                "plan_graph",
                "agent_task_contract",
                "canonical_events",
                "idempotent_task_create",
                "background_durable_runner",
                "execution_unit_registry",
                "channel_registry",
                "adapter_selection",
                "dispatch_decision",
                "durable_workflow",
                "artifact_registry",
                "evaluation_registry",
                "retry_replay",
                "admin_overview",
                "tenant_admin",
                "rbac_policy_registry",
                "bot_webhook_channels",
                "ha_profile",
                "workflow_engine_registry",
            ],
            "adapters": self.adapter_catalog(),
            "runtime": {
                "durable_engine": f"{self._db.dialect}-runner",
                "production_target": "temporal",
                "event_source": "v2_events",
            },
        }

    def create_task(
        self,
        payload: dict[str, Any],
        *,
        principal: str,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        goal = str(payload.get("goal") or payload.get("message") or "").strip()
        if not goal:
            raise ValueError("goal is required")
        with self._lock:
            if idempotency_key:
                existing = self._find_task_by_idempotency_key(idempotency_key)
                if existing is not None:
                    return existing

            now = utc_now()
            task_id = f"task_{uuid4().hex}"
            mode = normalize_choice(payload.get("mode"), SUPPORTED_MODES, "auto")
            channel = normalize_choice(payload.get("channel"), SUPPORTED_CHANNELS, "web")
            requested_adapter = normalize_choice(
                payload.get("adapter"),
                SUPPORTED_ADAPTERS,
                "auto",
            )
            workspace = normalize_workspace_contract(
                payload.get("workspace") or payload.get("repo")
            )
            if workspace:
                if mode != "single":
                    raise ValueError("real repository tasks require mode=single")
                if requested_adapter in {"auto", "fake"}:
                    raise ValueError(
                        "real repository tasks require an explicit real CLI adapter"
                    )
                if not workspace.get("test_command"):
                    raise ValueError(
                        "real repository tasks require workspace.test_command"
                    )
            project_id = str(payload.get("project_id") or "project_default")
            tenant_id = str(payload.get("tenant_id") or "tenant_default")
            title = summarize_goal(goal)
            strategy = self._strategy_for(goal, mode)
            dispatch = self._dispatch_decision(
                requested_adapter=requested_adapter,
                channel=channel,
                strategy=strategy,
                execution_unit_id=(
                    str(workspace["execution_unit_id"]) if workspace else None
                ),
                require_remote=bool(workspace),
            )
            adapter = str(dispatch["adapter"])
            metadata = dict(payload.get("metadata") or {})
            if workspace:
                metadata["workspace"] = workspace
            metadata.update(
                {
                    "source": payload.get("source") or channel,
                    "priority": payload.get("priority") or "normal",
                    "dispatch": dispatch,
                }
            )

            self._db.execute(
                """
                INSERT INTO v2_tasks (
                    task_id, tenant_id, project_id, created_by, title, goal,
                    mode, status, priority, channel, adapter, idempotency_key,
                    metadata_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    tenant_id,
                    project_id,
                    principal,
                    title,
                    goal,
                    mode,
                    "queued",
                    str(metadata["priority"]),
                    channel,
                    adapter,
                    idempotency_key,
                    json_dumps(metadata),
                    now,
                    now,
                ),
            )
            plan = self._create_plan(task_id, goal, mode, adapter, now)
            self._create_workflow_run_locked(task_id, plan, now)
            self._append_event_locked(
                task_id,
                "task.created",
                "system",
                {
                    "title": title,
                    "goal": goal,
                    "mode": mode,
                    "channel": channel,
                    "plan_id": plan["plan_id"],
                },
            )
            self._append_event_locked(
                task_id,
                "plan.created",
                "brain",
                {
                    "plan_id": plan["plan_id"],
                    "strategy": plan["strategy"],
                    "agent_task_count": len(plan["agent_tasks"]),
                },
            )
            self._append_event_locked(
                task_id,
                "dispatch.selected",
                "scheduler",
                dispatch,
            )
            self._db.commit()
            task = self.get_task(task_id)
        if not self._task_uses_remote_unit(task_id):
            self._ensure_runner(task_id)
        return task

    def list_tasks(
        self,
        *,
        principal: str | None = None,
        roles: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                """
                SELECT * FROM v2_tasks
                ORDER BY updated_at DESC, created_at DESC
                """
            ).fetchall()
            return [
                self._task_summary_from_row(row)
                for row in rows
                if self.can_access_task(row["task_id"], principal, roles)
            ]

    def get_task(self, task_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._task_row(task_id)
            if row is None:
                raise KeyError(task_id)
            task = dict(row)
            task["metadata"] = json_loads(task.pop("metadata_json"))
            task["plan"] = self._plan_for_task(task_id)
            task["events"] = self.events(task_id)
            task["progress"] = self._progress(task_id)
            task["execution_mode"] = self._execution_mode(task_id)
            task["result"] = self._result(task_id)
            return task

    def events(self, task_id: str, after: int = 0) -> list[dict[str, Any]]:
        with self._lock:
            if self._task_row(task_id) is None:
                raise KeyError(task_id)
            rows = self._db.execute(
                """
                SELECT * FROM v2_events
                WHERE task_id = ? AND sequence > ?
                ORDER BY sequence ASC
                """,
                (task_id, after),
            ).fetchall()
            return [event_from_row(row) for row in rows]

    def append_message(
        self,
        task_id: str,
        message: str,
        *,
        principal: str,
    ) -> dict[str, Any]:
        message = message.strip()
        if not message:
            raise ValueError("message is required")
        with self._lock:
            if self._task_row(task_id) is None:
                raise KeyError(task_id)
            event = self._append_event_locked(
                task_id,
                "user.message",
                principal,
                {"message": message},
            )
            self._touch_task_locked(task_id)
            self._db.commit()
            return event

    def admin_overview(self) -> dict[str, Any]:
        with self._lock:
            task_counts = {
                row["status"]: row["count"]
                for row in self._db.execute(
                    "SELECT status, COUNT(*) AS count FROM v2_tasks GROUP BY status"
                ).fetchall()
            }
            agent_counts = {
                row["status"]: row["count"]
                for row in self._db.execute(
                    "SELECT status, COUNT(*) AS count FROM v2_agent_tasks GROUP BY status"
                ).fetchall()
            }
            return {
                "generated_at": utc_now(),
                "tasks": {
                    "total": sum(task_counts.values()),
                    "by_status": task_counts,
                },
                "agent_tasks": {
                    "total": sum(agent_counts.values()),
                    "by_status": agent_counts,
                },
                "execution_units": self.execution_units(),
                "channels": self.channels(),
                "tenants": self.tenants(),
                "ha": self.ha_config(),
                "reliability": {
                    "idempotency": "enabled",
                    "event_source": "sqlite:v2_events",
                    "runner": self.workflow_engine_status()["active_engine"],
                    "production_runner": "Temporal",
                },
            }

    def execution_units(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM v2_execution_units ORDER BY updated_at DESC"
            ).fetchall()
            return [unit_from_row(row) for row in rows]

    def register_execution_unit(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        unit_id = str(payload.get("unit_id") or f"unit_{uuid4().hex}").strip()
        if not unit_id:
            raise ValueError("unit_id is required")
        with self._lock:
            self._db.execute(
                """
                INSERT INTO v2_execution_units (
                    unit_id, kind, status, labels_json, resources_json,
                    adapters_json, features_json, heartbeat_at, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(unit_id) DO UPDATE SET
                    kind = excluded.kind,
                    status = excluded.status,
                    labels_json = excluded.labels_json,
                    resources_json = excluded.resources_json,
                    adapters_json = excluded.adapters_json,
                    features_json = excluded.features_json,
                    heartbeat_at = excluded.heartbeat_at,
                    updated_at = excluded.updated_at
                """,
                (
                    unit_id,
                    str(payload.get("kind") or "local"),
                    str(payload.get("status") or "active"),
                    json_dumps(payload.get("labels") or {}),
                    json_dumps(payload.get("resources") or {}),
                    json_dumps(payload.get("adapters") or ["fake"]),
                    json_dumps(payload.get("features") or []),
                    now,
                    now,
                    now,
                ),
            )
            self._db.commit()
            return next(unit for unit in self.execution_units() if unit["unit_id"] == unit_id)

    def heartbeat_execution_worker(
        self,
        worker_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        worker_id = worker_id.strip()
        if not worker_id:
            raise ValueError("worker_id is required")
        unit = self.register_execution_unit(
            {
                "unit_id": worker_id,
                "kind": payload.get("kind") or "remote-worker",
                "status": payload.get("status") or "active",
                "labels": payload.get("labels") or payload.get("metadata") or {},
                "resources": payload.get("resources") or {},
                "adapters": payload.get("adapters") or ["fake"],
                "features": list(
                    dict.fromkeys(
                        [*(payload.get("features") or []), "remote-worker", "v2-agent-tasks"]
                    )
                ),
            }
        )
        with self._lock:
            self._extend_worker_leases_locked(
                worker_id,
                int(payload.get("lease_ttl_seconds") or 60),
            )
            self._db.commit()
        return unit

    def claim_remote_agent_task(
        self,
        worker_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        adapters = {
            str(item).strip()
            for item in payload.get("adapters") or []
            if str(item).strip()
        }
        lease_ttl = max(15, min(int(payload.get("lease_ttl_seconds") or 60), 600))
        with self._lock:
            self._reclaim_expired_agent_leases_locked()
            unit = next(
                (item for item in self.execution_units() if item["unit_id"] == worker_id),
                None,
            )
            if unit is None or unit["status"] != "active":
                return {"assignment": None, "reason": "worker_not_active"}
            supported = adapters or set(unit["adapters"])
            for agent in self._queued_remote_agents_locked(worker_id):
                if agent["adapter"] not in supported:
                    continue
                if not self._dependencies_completed_locked(agent):
                    continue
                task_id = str(agent["task_id"])
                token = secrets.token_urlsafe(32)
                now = utc_now()
                expires_at = lease_expiry(lease_ttl)
                existing = self._db.execute(
                    "SELECT attempt FROM v2_agent_leases WHERE agent_task_id = ?",
                    (agent["agent_task_id"],),
                ).fetchone()
                attempt = int(existing["attempt"]) + 1 if existing else 1
                self._db.execute(
                    """
                    INSERT INTO v2_agent_leases (
                        agent_task_id, task_id, worker_id, lease_hash, status,
                        attempt, expires_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(agent_task_id) DO UPDATE SET
                        worker_id = excluded.worker_id,
                        lease_hash = excluded.lease_hash,
                        status = excluded.status,
                        attempt = excluded.attempt,
                        expires_at = excluded.expires_at,
                        updated_at = excluded.updated_at
                    """,
                    (
                        agent["agent_task_id"],
                        task_id,
                        worker_id,
                        secret_hash(token),
                        "active",
                        attempt,
                        expires_at,
                        now,
                        now,
                    ),
                )
                task_row = self._task_row(task_id)
                if task_row is not None and task_row["status"] == "queued":
                    self._set_task_status_locked(task_id, "running")
                    self._set_workflow_status_locked(task_id, "running")
                    self._append_event_locked(
                        task_id,
                        "task.started",
                        "orchestrator",
                        {"runner": "remote-worker", "execution_unit_id": worker_id},
                    )
                step_id = self._start_workflow_step_locked(task_id, agent, now)
                self._transition_agent_status_locked(
                    agent["agent_task_id"], "running", started_at=now
                )
                self._append_event_locked(
                    task_id,
                    "agent_task.started",
                    agent["role"],
                    {
                        "agent_task_id": agent["agent_task_id"],
                        "adapter": agent["adapter"],
                        "execution_unit_id": worker_id,
                        "attempt": attempt,
                    },
                )
                self._db.commit()
                return {
                    "assignment": {
                        "task_id": task_id,
                        "agent_task_id": agent["agent_task_id"],
                        "step_id": step_id,
                        "lease_token": token,
                        "lease_expires_at": expires_at,
                        "attempt": attempt,
                        "worker_id": worker_id,
                        "adapter": agent["adapter"],
                        "role": agent["role"],
                        "goal": agent["goal"],
                        "depends_on": agent["depends_on"],
                        "artifact_contract": agent["artifact_contract"],
                        "workspace": self._workspace_contract_for_task(task_id),
                    }
                }
            self._db.commit()
            return {"assignment": None, "reason": "no_matching_agent_task"}

    def remote_agent_control(self, worker_id: str) -> dict[str, Any]:
        with self._lock:
            self._reclaim_expired_agent_leases_locked()
            rows = self._db.execute(
                """
                SELECT l.agent_task_id, l.task_id, l.expires_at, t.status AS task_status
                FROM v2_agent_leases l
                JOIN v2_tasks t ON t.task_id = l.task_id
                WHERE l.worker_id = ? AND l.status = 'active'
                ORDER BY l.updated_at ASC
                """,
                (worker_id,),
            ).fetchall()
            permissions = self._db.execute(
                """
                SELECT p.* FROM v2_permissions p
                JOIN v2_agent_leases l ON l.agent_task_id = p.agent_task_id
                WHERE l.worker_id = ? AND p.status = 'resolved' AND p.delivered_at IS NULL
                ORDER BY p.updated_at ASC
                """,
                (worker_id,),
            ).fetchall()
            return {
                "actions": [
                    {
                        "type": "cancel",
                        "task_id": row["task_id"],
                        "agent_task_id": row["agent_task_id"],
                    }
                    for row in rows
                    if row["task_status"] == "cancelled"
                ],
                "permissions": [permission_from_row(row) for row in permissions],
            }

    def append_remote_agent_event(
        self,
        worker_id: str,
        agent_task_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        with self._lock:
            lease = self._require_agent_lease_locked(
                worker_id,
                agent_task_id,
                str(payload.get("lease_token") or ""),
            )
            event_type = str(payload.get("type") or "agent.message")
            data = redact_secret_config(dict(payload.get("payload") or {}))
            agent = self._agent_task_row(agent_task_id)
            if event_type == "permission.requested":
                permission_id = str(data.get("permission_id") or f"perm_{uuid4().hex}")
                data["permission_id"] = permission_id
            data = validate_worker_event(event_type, data)
            if event_type == "permission.requested":
                now = utc_now()
                self._db.execute(
                    """
                    INSERT INTO v2_permissions (
                        permission_id, task_id, agent_task_id, worker_id, status,
                        request_json, decision_json, created_at, updated_at, delivered_at
                    ) VALUES (?, ?, ?, ?, 'pending', ?, '{}', ?, ?, NULL)
                    ON CONFLICT(permission_id) DO NOTHING
                    """,
                    (
                        permission_id,
                        lease["task_id"],
                        agent_task_id,
                        worker_id,
                        json_dumps(data),
                        now,
                        now,
                    ),
                )
            data.update(
                {
                    "attempt": int(lease["attempt"]),
                    "execution_unit_id": worker_id,
                }
            )
            source_event_id = str(payload.get("source_event_id") or "").strip()[:240]
            if source_event_id:
                duplicate = self._db.execute(
                    """
                    SELECT e.* FROM v2_event_dedup d
                    JOIN v2_events e ON e.event_id = d.event_id
                    WHERE d.task_id = ? AND d.agent_task_id = ?
                        AND d.attempt = ? AND d.source_event_id = ?
                    """,
                    (
                        lease["task_id"],
                        agent_task_id,
                        int(lease["attempt"]),
                        source_event_id,
                    ),
                ).fetchone()
                if duplicate is not None:
                    return event_from_row(duplicate)
            event = self._append_event_locked(
                lease["task_id"],
                event_type,
                agent["role"],
                {"agent_task_id": agent_task_id, **data},
            )
            if source_event_id:
                self._db.execute(
                    """
                    INSERT INTO v2_event_dedup (
                        task_id, agent_task_id, attempt, source_event_id,
                        event_id, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        lease["task_id"],
                        agent_task_id,
                        int(lease["attempt"]),
                        source_event_id,
                        event["event_id"],
                        event["created_at"],
                    ),
                )
            self._db.commit()
            return event

    def complete_remote_agent_task(
        self,
        worker_id: str,
        agent_task_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        with self._lock:
            lease = self._require_agent_lease_locked(
                worker_id,
                agent_task_id,
                str(payload.get("lease_token") or ""),
                allowed_statuses={"active", "completed"},
            )
            if lease["status"] == "completed":
                return self.get_task(lease["task_id"])
            task_row = self._task_row(lease["task_id"])
            if task_row is not None and task_row["status"] == "cancelled":
                raise PermissionError("task was cancelled")
            agent = self._agent_task_row(agent_task_id)
            summary = str(payload.get("summary") or payload.get("message") or "").strip()
            if not summary:
                raise ValueError("summary is required")
            adapter_result = redact_secret_config(
                {
                    "adapter": agent["adapter"],
                    "protocol": payload.get("protocol") or "ACP/A2A",
                    "execution_mode": payload.get("execution_mode") or "real-cli",
                    "exit_code": payload.get("exit_code", 0),
                    "summary": summary[:4000],
                    "worker_id": worker_id,
                }
            )
            result = {
                "final_summary": summary[:4000],
                "quality": "contract-passed",
                "adapter": adapter_result,
            }
            artifact = self._write_artifact_locked(
                lease["task_id"],
                agent_task_id,
                "final_summary",
                "summary",
                result,
            )
            for item in payload.get("artifacts") or []:
                if not isinstance(item, dict):
                    continue
                self._write_artifact_locked(
                    lease["task_id"],
                    agent_task_id,
                    str(item.get("name") or "worker_artifact")[:120],
                    str(item.get("kind") or "file")[:40],
                    redact_secret_config(dict(item.get("content") or {})),
                )
            evaluation = self._write_evaluation_locked(
                lease["task_id"],
                agent_task_id,
                "contract",
                "passed",
                {"checks": ["non_empty_summary"], "artifact_id": artifact["artifact_id"]},
            )
            completed_at = utc_now()
            self._transition_agent_status_locked(
                agent_task_id,
                "completed",
                result=result,
                completed_at=completed_at,
            )
            self._finish_remote_step_locked(
                lease["task_id"], agent_task_id, "completed", artifact, completed_at
            )
            self._db.execute(
                """
                UPDATE v2_agent_leases SET status = 'completed', updated_at = ?
                WHERE agent_task_id = ?
                """,
                (completed_at, agent_task_id),
            )
            self._append_event_locked(
                lease["task_id"],
                "agent_task.completed",
                agent["role"],
                {
                    "agent_task_id": agent_task_id,
                    "result": result,
                    "artifact_id": artifact["artifact_id"],
                    "evaluation_id": evaluation["evaluation_id"],
                    "execution_unit_id": worker_id,
                },
            )
            self._complete_task_if_ready_locked(lease["task_id"])
            self._db.commit()
            return self.get_task(lease["task_id"])

    def fail_remote_agent_task(
        self,
        worker_id: str,
        agent_task_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        with self._lock:
            lease = self._require_agent_lease_locked(
                worker_id,
                agent_task_id,
                str(payload.get("lease_token") or ""),
                allowed_statuses={"active", "failed", "retry", "cancelled"},
            )
            if lease["status"] != "active":
                return self.get_task(lease["task_id"])
            task_row = self._task_row(lease["task_id"])
            if task_row is not None and task_row["status"] == "cancelled":
                now = utc_now()
                self._db.execute(
                    """
                    UPDATE v2_agent_leases SET status = 'cancelled', updated_at = ?
                    WHERE agent_task_id = ?
                    """,
                    (now, agent_task_id),
                )
                self._db.commit()
                return self.get_task(lease["task_id"])
            reason = str(payload.get("error") or "remote agent failed")[:1200]
            now = utc_now()
            for item in payload.get("artifacts") or []:
                if not isinstance(item, dict):
                    continue
                self._write_artifact_locked(
                    lease["task_id"],
                    agent_task_id,
                    str(item.get("name") or "worker_failure")[:120],
                    str(item.get("kind") or "failure")[:40],
                    redact_secret_config(dict(item.get("content") or {})),
                )
            retryable = bool(payload.get("retryable", True)) and int(lease["attempt"]) < 2
            workspace_result = payload.get("workspace")
            if retryable and isinstance(workspace_result, dict):
                base_commit = str(workspace_result.get("base_commit") or "").strip()
                if base_commit and task_row is not None:
                    metadata = json_loads(task_row["metadata_json"])
                    workspace = (
                        metadata.get("workspace") if isinstance(metadata, dict) else None
                    )
                    if isinstance(workspace, dict):
                        workspace["ref"] = base_commit
                        self._db.execute(
                            "UPDATE v2_tasks SET metadata_json = ?, updated_at = ? "
                            "WHERE task_id = ?",
                            (json_dumps(metadata), now, lease["task_id"]),
                        )
            next_status = "queued" if retryable else "failed"
            self._transition_agent_status_locked(agent_task_id, next_status)
            self._db.execute(
                "UPDATE v2_agent_leases SET status = ?, updated_at = ? WHERE agent_task_id = ?",
                ("retry" if retryable else "failed", now, agent_task_id),
            )
            self._append_event_locked(
                lease["task_id"],
                "agent_task.retry_scheduled" if retryable else "agent_task.failed",
                "remote-worker",
                {
                    "agent_task_id": agent_task_id,
                    "worker_id": worker_id,
                    "reason": reason,
                    "attempt": lease["attempt"],
                },
            )
            self._finish_remote_step_locked(
                lease["task_id"],
                agent_task_id,
                "failed",
                {"error": reason, "retrying": retryable},
                now,
            )
            if not retryable:
                self._set_task_status_locked(lease["task_id"], "failed")
                self._set_workflow_status_locked(lease["task_id"], "failed")
                self._append_event_locked(
                    lease["task_id"],
                    "task.failed",
                    "orchestrator",
                    {"error": reason, "failure_summary": failure_summary(RuntimeError(reason))},
                )
            self._db.commit()
            return self.get_task(lease["task_id"])

    def discover_execution_units(self) -> dict[str, Any]:
        configured = os.environ.get("V2_EXECUTION_UNITS_JSON")
        discovered = []
        if configured:
            payload = json.loads(configured)
            if not isinstance(payload, list):
                raise ValueError("V2_EXECUTION_UNITS_JSON must be a JSON array")
            for item in payload:
                if not isinstance(item, dict):
                    raise ValueError("execution unit entries must be JSON objects")
                discovered.append(self.register_execution_unit(item))
        return {
            "units": self.execution_units(),
            "discovered": discovered,
            "source": "V2_EXECUTION_UNITS_JSON" if configured else "registry",
            "supported_kinds": ["local-workspace", "docker", "ecs", "nas"],
        }

    def channels(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM v2_channels ORDER BY platform ASC"
            ).fetchall()
            return [channel_from_row(row) for row in rows]

    def configure_channel(self, platform: str, payload: dict[str, Any]) -> dict[str, Any]:
        platform = normalize_choice(platform, SUPPORTED_CHANNELS, "")
        if not platform:
            raise ValueError("unsupported channel platform")
        now = utc_now()
        with self._lock:
            current = self._channel_config_raw(platform)
            config = dict(current)
            config.update(dict(payload.get("config") or payload))
            status = str(payload.get("status") or "configured")
            self._db.execute(
                """
                INSERT INTO v2_channels (
                    channel_id, platform, status, config_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(platform) DO UPDATE SET
                    status = excluded.status,
                    config_json = excluded.config_json,
                    updated_at = excluded.updated_at
                """,
                (
                    f"channel_{platform}",
                    platform,
                    status,
                    json_dumps(config),
                    now,
                    now,
                ),
            )
            self._db.commit()
            return self._channel_by_platform(platform)

    def channel_messages(self, platform: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            if platform:
                rows = self._db.execute(
                    """
                    SELECT * FROM v2_channel_messages
                    WHERE platform = ?
                    ORDER BY created_at DESC
                    """,
                    (platform,),
                ).fetchall()
            else:
                rows = self._db.execute(
                    """
                    SELECT * FROM v2_channel_messages
                    ORDER BY created_at DESC
                    LIMIT 100
                    """
                ).fetchall()
            return [channel_message_from_row(row) for row in rows]

    def receive_channel_message(
        self,
        platform: str,
        payload: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        platform = normalize_choice(platform, SUPPORTED_CHANNELS, "")
        if platform not in {"dingtalk", "feishu", "wecom", "web", "mobile"}:
            raise ValueError("unsupported channel platform")
        config = self._channel_config_raw(platform)
        self._validate_channel_callback(platform, config, headers or {}, payload)
        normalized = normalize_inbound_channel_payload(platform, payload)
        message = str(normalized.get("text") or "").strip()
        if not message:
            raise ValueError("message text is required")
        task = self.create_task(
            {
                "goal": message,
                "mode": normalized.get("mode") or "auto",
                "adapter": normalized.get("adapter") or "auto",
                "channel": platform,
                "tenant_id": normalized.get("tenant_id") or "tenant_default",
                "metadata": {
                    "external_message_id": normalized.get("external_message_id"),
                    "external_sender": normalized.get("sender"),
                    "raw_channel_payload": payload,
                },
                "source": platform,
            },
            principal=str(normalized.get("principal") or f"{platform}:bot"),
            idempotency_key=normalized.get("idempotency_key"),
        )
        record = self._record_channel_message(
            platform=platform,
            direction="inbound",
            status="accepted",
            task_id=task["task_id"],
            external_message_id=normalized.get("external_message_id"),
            sender=normalized.get("sender") or {},
            content={"text": message},
            raw=payload,
        )
        return {"accepted": True, "task": task, "message": record}

    def send_channel_message(
        self,
        platform: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        platform = normalize_choice(platform, SUPPORTED_CHANNELS, "")
        if platform not in SUPPORTED_CHANNELS:
            raise ValueError("unsupported channel platform")
        task_id = str(payload.get("task_id") or "").strip() or None
        text = str(payload.get("message") or payload.get("text") or "").strip()
        if not text:
            raise ValueError("message is required")
        config = self._channel_config_raw(platform)
        outbound_payload = outbound_channel_payload(platform, text)
        status = "sent"
        error = None
        webhook_url = str(config.get("webhook_url") or "").strip()
        if webhook_url:
            try:
                self._post_channel_webhook(webhook_url, outbound_payload)
            except RuntimeError as exc:
                status = "failed"
                error = str(exc)
        else:
            status = "queued"
            error = "webhook_url is not configured"
        record = self._record_channel_message(
            platform=platform,
            direction="outbound",
            status=status,
            task_id=task_id,
            external_message_id=None,
            sender={"system": "agentflow"},
            content=outbound_payload,
            raw=payload,
            error=error,
        )
        if task_id:
            with self._lock:
                if self._task_row(task_id) is not None:
                    self._append_event_locked(
                        task_id,
                        "channel.message_sent",
                        "channel-service",
                        {
                            "platform": platform,
                            "status": status,
                            "message_id": record["message_id"],
                            "error": error,
                        },
                    )
                    self._db.commit()
        return record

    def tenants(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM v2_tenants ORDER BY created_at ASC"
            ).fetchall()
            return [tenant_from_row(row) for row in rows]

    def projects(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM v2_projects ORDER BY created_at ASC"
            ).fetchall()
            return [project_from_row(row) for row in rows]

    def upsert_project(self, payload: dict[str, Any], *, principal: str) -> dict[str, Any]:
        project_id = str(payload.get("project_id") or f"project_{uuid4().hex}").strip()
        tenant_id = str(payload.get("tenant_id") or "tenant_default").strip()
        name = str(payload.get("name") or project_id).strip()
        if not project_id or not tenant_id or not name:
            raise ValueError("project_id, tenant_id, and name are required")
        now = utc_now()
        with self._lock:
            self._db.execute(
                """
                INSERT INTO v2_projects (
                    project_id, tenant_id, name, status, created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id) DO UPDATE SET
                    tenant_id = excluded.tenant_id,
                    name = excluded.name,
                    status = excluded.status,
                    updated_at = excluded.updated_at
                """,
                (
                    project_id,
                    tenant_id,
                    name,
                    str(payload.get("status") or "active"),
                    principal,
                    now,
                    now,
                ),
            )
            self._db.execute(
                """
                INSERT OR IGNORE INTO v2_project_members (
                    project_id, user_id, role, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (project_id, principal, "owner", "active", now, now),
            )
            self._db.commit()
            return next(item for item in self.projects() if item["project_id"] == project_id)

    def project_members(self, project_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                """
                SELECT * FROM v2_project_members
                WHERE project_id = ? ORDER BY created_at ASC
                """,
                (project_id,),
            ).fetchall()
            return [project_member_from_row(row) for row in rows]

    def upsert_project_member(
        self,
        project_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        user_id = str(payload.get("user_id") or payload.get("email") or "").strip()
        role = str(payload.get("role") or "member").strip()
        if not user_id or role not in {"owner", "editor", "viewer", "member"}:
            raise ValueError("user_id and a valid project role are required")
        now = utc_now()
        with self._lock:
            if not any(item["project_id"] == project_id for item in self.projects()):
                raise KeyError(project_id)
            self._db.execute(
                """
                INSERT INTO v2_project_members (
                    project_id, user_id, role, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id, user_id) DO UPDATE SET
                    role = excluded.role,
                    status = excluded.status,
                    updated_at = excluded.updated_at
                """,
                (
                    project_id,
                    user_id,
                    role,
                    str(payload.get("status") or "active"),
                    now,
                    now,
                ),
            )
            self._db.commit()
            return next(
                item for item in self.project_members(project_id) if item["user_id"] == user_id
            )

    def can_access_task(
        self,
        task_id: str,
        principal: str | None,
        roles: list[str] | None,
        *,
        write: bool = False,
    ) -> bool:
        with self._lock:
            row = self._task_row(task_id)
            if row is None:
                raise KeyError(task_id)
            role_set = set(roles or [])
            if principal in {None, "api-token"} or role_set.intersection(
                {"owner", "operator"}
            ):
                return True
            if principal == row["created_by"]:
                return True
            member = self._db.execute(
                """
                SELECT role, status FROM v2_project_members
                WHERE project_id = ? AND user_id = ?
                """,
                (row["project_id"], principal),
            ).fetchone()
            if member is None or member["status"] != "active":
                return False
            if not write:
                return True
            return member["role"] in {"owner", "editor", "member"}

    def can_access_project(
        self,
        project_id: str,
        principal: str | None,
        roles: list[str] | None,
        *,
        write: bool = False,
    ) -> bool:
        with self._lock:
            project = self._db.execute(
                """
                SELECT project_id FROM v2_projects
                WHERE project_id = ? AND status = 'active'
                """,
                (project_id,),
            ).fetchone()
            if project is None:
                raise KeyError(project_id)
            role_set = set(roles or [])
            if principal in {None, "api-token"} or role_set.intersection(
                {"owner", "operator"}
            ):
                return True
            member = self._db.execute(
                """
                SELECT role, status FROM v2_project_members
                WHERE project_id = ? AND user_id = ?
                """,
                (project_id, principal),
            ).fetchone()
            if member is None:
                return project_id == "project_default" and write
            if member["status"] != "active":
                return False
            return not write or member["role"] in {"owner", "editor", "member"}

    def upsert_tenant(self, payload: dict[str, Any], *, principal: str) -> dict[str, Any]:
        now = utc_now()
        tenant_id = str(payload.get("tenant_id") or f"tenant_{uuid4().hex}").strip()
        name = str(payload.get("name") or tenant_id).strip()
        if not tenant_id or not name:
            raise ValueError("tenant_id and name are required")
        status = str(payload.get("status") or "active")
        settings = dict(payload.get("settings") or {})
        with self._lock:
            self._db.execute(
                """
                INSERT INTO v2_tenants (
                    tenant_id, name, status, settings_json, created_by,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id) DO UPDATE SET
                    name = excluded.name,
                    status = excluded.status,
                    settings_json = excluded.settings_json,
                    updated_at = excluded.updated_at
                """,
                (tenant_id, name, status, json_dumps(settings), principal, now, now),
            )
            self._db.commit()
            return next(tenant for tenant in self.tenants() if tenant["tenant_id"] == tenant_id)

    def tenant_users(self, tenant_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                """
                SELECT * FROM v2_tenant_users
                WHERE tenant_id = ?
                ORDER BY created_at ASC
                """,
                (tenant_id,),
            ).fetchall()
            return [tenant_user_from_row(row) for row in rows]

    def upsert_tenant_user(self, tenant_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        email = str(payload.get("email") or payload.get("user_id") or "").strip()
        if not email:
            raise ValueError("email is required")
        roles = payload.get("roles") or ["member"]
        if not isinstance(roles, list) or not all(isinstance(role, str) for role in roles):
            raise ValueError("roles must be a list of strings")
        now = utc_now()
        with self._lock:
            self._db.execute(
                """
                INSERT INTO v2_tenant_users (
                    tenant_id, user_id, email, roles_json, status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id, user_id) DO UPDATE SET
                    email = excluded.email,
                    roles_json = excluded.roles_json,
                    status = excluded.status,
                    updated_at = excluded.updated_at
                """,
                (
                    tenant_id,
                    email,
                    email,
                    json_dumps(roles),
                    str(payload.get("status") or "active"),
                    now,
                    now,
                ),
            )
            self._db.commit()
            return next(user for user in self.tenant_users(tenant_id) if user["user_id"] == email)

    def rbac_policies(self, tenant_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                """
                SELECT * FROM v2_rbac_policies
                WHERE tenant_id = ?
                ORDER BY role ASC
                """,
                (tenant_id,),
            ).fetchall()
            return [rbac_policy_from_row(row) for row in rows]

    def upsert_rbac_policy(
        self,
        tenant_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        role = str(payload.get("role") or "").strip()
        permissions = payload.get("permissions") or []
        if not role:
            raise ValueError("role is required")
        if not isinstance(permissions, list) or not all(
            isinstance(item, str) for item in permissions
        ):
            raise ValueError("permissions must be a list of strings")
        now = utc_now()
        with self._lock:
            self._db.execute(
                """
                INSERT INTO v2_rbac_policies (
                    tenant_id, role, permissions_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id, role) DO UPDATE SET
                    permissions_json = excluded.permissions_json,
                    updated_at = excluded.updated_at
                """,
                (tenant_id, role, json_dumps(permissions), now, now),
            )
            self._db.commit()
            return next(
                policy for policy in self.rbac_policies(tenant_id) if policy["role"] == role
            )

    def ha_config(self) -> dict[str, Any]:
        database_url = os.environ.get("V2_DATABASE_URL") or os.environ.get("DATABASE_URL")
        queue_url = os.environ.get("V2_QUEUE_URL") or os.environ.get("REDIS_URL")
        temporal_address = os.environ.get("TEMPORAL_ADDRESS")
        profile = os.environ.get("V2_DEPLOYMENT_PROFILE") or "local-2c2g"
        return {
            "profile": profile,
            "database": {
                "driver": self._db.dialect,
                "configured": bool(database_url),
                "url_env": "V2_DATABASE_URL" if os.environ.get("V2_DATABASE_URL") else None,
                "shared_v2_domain_state": self._db.dialect == "postgres",
                "multi_control_plane_ready": self._db.dialect == "postgres",
            },
            "queue": {
                "driver": "redis" if queue_url else "sqlite-lease",
                "configured": bool(queue_url),
                "url_env": "V2_QUEUE_URL" if os.environ.get("V2_QUEUE_URL") else None,
            },
            "workers": {
                "horizontal_scale": bool(queue_url) and self._db.dialect == "postgres",
                "requires_remote_execution_units": self._db.dialect == "postgres",
                "concurrency": int(os.environ.get("V2_WORKER_CONCURRENCY") or "1"),
                "role": os.environ.get("V2_PROCESS_ROLE") or "runtime",
            },
            "workflow": self.workflow_engine_status(),
            "backup": {
                "enabled": os.environ.get("V2_BACKUP_ENABLED", "1") == "1",
                "target": os.environ.get("V2_BACKUP_TARGET") or "local-artifacts",
            },
            "resource_fit": {
                "two_c_two_g": profile == "local-2c2g",
                "recommendation": (
                    "Use local profile on 2C2G; use HA profile with external DB/queue."
                ),
            },
        }

    def workflow_engine_status(self) -> dict[str, Any]:
        temporal_address = os.environ.get("TEMPORAL_ADDRESS")
        engine = os.environ.get("V2_WORKFLOW_ENGINE") or (
            "temporal" if temporal_address else "local-sqlite-dag"
        )
        return {
            "active_engine": engine,
            "engines": [
                {
                    "engine": "local-sqlite-dag",
                    "status": "available",
                    "durability": "process-recovered sqlite state",
                },
                {
                    "engine": "temporal",
                    "status": "configured" if temporal_address else "available",
                    "address": temporal_address or "",
                    "task_queue": os.environ.get("TEMPORAL_TASK_QUEUE")
                    or "agentflow-v2",
                    "durability": "external workflow history and activity retry",
                },
            ],
        }

    def workflow(self, task_id: str) -> dict[str, Any]:
        with self._lock:
            if self._task_row(task_id) is None:
                raise KeyError(task_id)
            run = self._workflow_run(task_id)
            steps = self._db.execute(
                """
                SELECT * FROM v2_workflow_steps
                WHERE task_id = ?
                ORDER BY order_index ASC, created_at ASC
                """,
                (task_id,),
            ).fetchall()
            return {
                "run": workflow_run_from_row(run) if run is not None else None,
                "steps": [workflow_step_from_row(row) for row in steps],
            }

    def artifacts(self, task_id: str) -> list[dict[str, Any]]:
        with self._lock:
            if self._task_row(task_id) is None:
                raise KeyError(task_id)
            rows = self._db.execute(
                """
                SELECT * FROM v2_artifacts
                WHERE task_id = ?
                ORDER BY created_at ASC
                """,
                (task_id,),
            ).fetchall()
            return [artifact_from_row(row) for row in rows]

    def artifact(self, task_id: str, artifact_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM v2_artifacts WHERE task_id = ? AND artifact_id = ?",
                (task_id, artifact_id),
            ).fetchone()
            if row is None:
                raise KeyError(artifact_id)
            return artifact_from_row(row)

    def audit_bundle(self, task_id: str) -> dict[str, Any]:
        return {
            "schema": "agentflow-v2-task-audit/v1",
            "generated_at": utc_now(),
            "task": self.get_task(task_id),
            "workflow": self.workflow(task_id),
            "events": self.events(task_id),
            "artifacts": self.artifacts(task_id),
            "evaluations": self.evaluations(task_id),
            "replays": self.replays(task_id),
        }

    def evaluations(self, task_id: str) -> list[dict[str, Any]]:
        with self._lock:
            if self._task_row(task_id) is None:
                raise KeyError(task_id)
            rows = self._db.execute(
                """
                SELECT * FROM v2_evaluations
                WHERE task_id = ?
                ORDER BY created_at ASC
                """,
                (task_id,),
            ).fetchall()
            return [evaluation_from_row(row) for row in rows]

    def replays(self, task_id: str) -> list[dict[str, Any]]:
        with self._lock:
            if self._task_row(task_id) is None:
                raise KeyError(task_id)
            rows = self._db.execute(
                """
                SELECT * FROM v2_replays
                WHERE task_id = ?
                ORDER BY created_at DESC
                """,
                (task_id,),
            ).fetchall()
            return [replay_from_row(row) for row in rows]

    def webshell_events(self, task_id: str) -> list[dict[str, Any]]:
        return [
            v2_event_to_daemon_event(event)
            for event in self.events(task_id)
            if is_v2_webshell_event(event)
        ]

    def retry_task(self, task_id: str, *, principal: str) -> dict[str, Any]:
        with self._lock:
            row = self._task_row(task_id)
            if row is None:
                raise KeyError(task_id)
            if row["status"] == "running":
                raise ValueError("task is already running")
            now = utc_now()
            for agent in self._agent_tasks(task_id):
                self._transition_agent_status_locked(
                    agent["agent_task_id"], "queued", reset_result=True
                )
            self._set_task_status_locked(task_id, "queued")
            current = self._workflow_run(task_id)
            attempt = 1 if current is None else int(current["attempt"]) + 1
            self._db.execute(
                """
                UPDATE v2_workflow_runs
                SET status = ?, attempt = ?, updated_at = ?
                WHERE task_id = ?
                """,
                ("queued", attempt, now, task_id),
            )
            self._append_event_locked(
                task_id,
                "task.retry_requested",
                principal,
                {"attempt": attempt},
            )
            self._db.commit()
        if not self._task_uses_remote_unit(task_id):
            self._ensure_runner(task_id)
        return self.get_task(task_id)

    def cancel_task(
        self,
        task_id: str,
        *,
        principal: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            row = self._task_row(task_id)
            if row is None:
                raise KeyError(task_id)
            if row["status"] in TERMINAL_TASK_STATUSES:
                return self.get_task(task_id)
            now = utc_now()
            self._set_task_status_locked(task_id, "cancelled")
            self._set_workflow_status_locked(task_id, "cancelled")
            for agent in self._agent_tasks(task_id):
                if agent["status"] not in TERMINAL_TASK_STATUSES:
                    self._transition_agent_status_locked(
                        agent["agent_task_id"], "cancelled", completed_at=now
                    )
            self._append_event_locked(
                task_id,
                "task.cancelled",
                principal,
                {"reason": reason or "cancelled by user"},
            )
            self._db.commit()
            return self.get_task(task_id)

    def resolve_task_permission(
        self,
        task_id: str,
        permission_id: str,
        payload: dict[str, Any],
        *,
        principal: str,
    ) -> dict[str, Any]:
        decision = str(payload.get("decision") or "").strip().lower()
        if decision not in {"allow", "deny", "allow_once", "allow_always"}:
            raise ValueError("decision must be allow, deny, allow_once, or allow_always")
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM v2_permissions WHERE permission_id = ? AND task_id = ?",
                (permission_id, task_id),
            ).fetchone()
            if row is None:
                raise KeyError(permission_id)
            now = utc_now()
            decision_payload = {
                "decision": decision,
                "decided_by": principal,
                "reason": str(payload.get("reason") or "")[:500],
            }
            self._db.execute(
                """
                UPDATE v2_permissions
                SET status = 'resolved', decision_json = ?, updated_at = ?
                WHERE permission_id = ?
                """,
                (json_dumps(decision_payload), now, permission_id),
            )
            self._append_event_locked(
                task_id,
                "permission.resolved",
                principal,
                {"permission_id": permission_id, **decision_payload},
            )
            self._db.commit()
            resolved = self._db.execute(
                "SELECT * FROM v2_permissions WHERE permission_id = ?",
                (permission_id,),
            ).fetchone()
            return permission_from_row(resolved)

    def task_permissions(self, task_id: str) -> list[dict[str, Any]]:
        with self._lock:
            if self._task_row(task_id) is None:
                raise KeyError(task_id)
            rows = self._db.execute(
                """
                SELECT * FROM v2_permissions
                WHERE task_id = ? ORDER BY created_at ASC
                """,
                (task_id,),
            ).fetchall()
            return [permission_from_row(row) for row in rows]

    def replay_task(self, task_id: str, *, principal: str) -> dict[str, Any]:
        with self._lock:
            task = self.get_task(task_id)
            replay_id = f"replay_{uuid4().hex}"
            events = self.events(task_id)
            replay = {
                "task": task,
                "workflow": self.workflow(task_id),
                "events": events,
                "artifacts": self.artifacts(task_id),
                "evaluations": self.evaluations(task_id),
            }
            now = utc_now()
            self._db.execute(
                """
                INSERT INTO v2_replays (
                    replay_id, task_id, requested_by, status, snapshot_json,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (replay_id, task_id, principal, "created", json_dumps(replay), now),
            )
            self._append_event_locked(
                task_id,
                "task.replay_created",
                principal,
                {"replay_id": replay_id, "event_count": len(events)},
            )
            self._db.commit()
            return self.replays(task_id)[0]

    def adapter_catalog(self) -> list[dict[str, Any]]:
        units = self.execution_units()
        configured = {
            adapter
            for unit in units
            if unit["status"] == "active"
            for adapter in unit["adapters"]
        }
        return [
            {
                "adapter": adapter,
                "label": label,
                "status": "available" if adapter in configured else default_status,
                "protocol": protocol,
                "execution": execution,
            }
            for adapter, label, protocol, execution, default_status in [
                ("fake", "Fake smoke runner", "internal", "local-simulated", "available"),
                ("qwen", "qwen-code", "ACP/A2A", "cli-adapter", "registered"),
                ("codex", "codex cli", "ACP/A2A", "cli-adapter", "registered"),
                ("claude", "claude code", "ACP/A2A", "cli-adapter", "registered"),
                ("opencode", "opencode", "ACP/A2A", "cli-adapter", "registered"),
            ]
        ]

    def _create_plan(
        self,
        task_id: str,
        goal: str,
        mode: str,
        adapter: str,
        now: str,
    ) -> dict[str, Any]:
        strategy = self._strategy_for(goal, mode)
        if strategy == "orchestrator-workers":
            strategy = "orchestrator-workers"
            agent_specs = [
                (
                    "brain",
                    "Plan the work",
                    f"Plan this user goal without changing files: {goal}",
                    [],
                ),
                (
                    "builder",
                    "Execute the work",
                    f"Implement this user goal in the assigned workspace: {goal}",
                    ["brain"],
                ),
                (
                    "reviewer",
                    "Review and package",
                    f"Review the implementation for this user goal and report gaps: {goal}",
                    ["builder"],
                ),
            ]
        else:
            strategy = "single-agent-fast-path"
            agent_specs = [
                ("agent", "Complete the task", goal, []),
            ]
        plan_id = f"plan_{uuid4().hex}"
        graph = {
            "strategy": strategy,
            "execution": "serial" if strategy == "orchestrator-workers" else "single",
            "nodes": [
                {
                    "id": role,
                    "title": title,
                    "depends_on": depends_on,
                }
                for role, title, _agent_goal, depends_on in agent_specs
            ],
        }
        artifact_contract = {
            "required": ["final_summary"],
            "optional": ["patch", "report", "test_results"],
            "evaluation": ["contract", "execution", "review"],
        }
        self._db.execute(
            """
            INSERT INTO v2_plans (
                plan_id, task_id, version, status, strategy, graph_json,
                artifact_contract_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                plan_id,
                task_id,
                1,
                "active",
                strategy,
                json_dumps(graph),
                json_dumps(artifact_contract),
                now,
                now,
            ),
        )
        agent_tasks = []
        for order_index, (role, title, agent_goal, depends_on) in enumerate(agent_specs):
            agent_task_id = f"at_{uuid4().hex}"
            contract = {
                "goal": agent_goal,
                "artifacts": ["final_summary"],
                "evaluation": "must produce non-empty result summary",
            }
            self._db.execute(
                """
                INSERT INTO v2_agent_tasks (
                    agent_task_id, task_id, plan_id, role, title, goal,
                    status, adapter, order_index, depends_on_json,
                    artifact_contract_json, result_json, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    agent_task_id,
                    task_id,
                    plan_id,
                    role,
                    title,
                    agent_goal,
                    "queued",
                    adapter,
                    order_index,
                    json_dumps(depends_on),
                    json_dumps(contract),
                    json_dumps({}),
                    now,
                ),
            )
            agent_tasks.append(
                {
                    "agent_task_id": agent_task_id,
                    "role": role,
                    "title": title,
                    "goal": agent_goal,
                    "status": "queued",
                    "depends_on": depends_on,
                    "artifact_contract": contract,
                }
            )
        return {
            "plan_id": plan_id,
            "strategy": strategy,
            "graph": graph,
            "artifact_contract": artifact_contract,
            "agent_tasks": agent_tasks,
        }

    def _strategy_for(self, goal: str, mode: str) -> str:
        if mode == "single":
            return "single-agent-fast-path"
        complex_task = mode in {"multi-agent", "workflow"} or len(goal) > 160
        return "orchestrator-workers" if complex_task else "single-agent-fast-path"

    def _workspace_contract_for_task(self, task_id: str) -> dict[str, Any]:
        row = self._task_row(task_id)
        metadata = json_loads(row["metadata_json"]) if row is not None else {}
        workspace = metadata.get("workspace") if isinstance(metadata, dict) else None
        if isinstance(workspace, dict):
            return dict(workspace)
        return {"strategy": "isolated-directory"}

    def _dispatch_decision(
        self,
        *,
        requested_adapter: str,
        channel: str,
        strategy: str,
        execution_unit_id: str | None = None,
        require_remote: bool = False,
    ) -> dict[str, Any]:
        adapter = "fake" if requested_adapter == "auto" else requested_adapter
        unit = self._select_execution_unit(
            adapter,
            execution_unit_id=execution_unit_id,
            require_remote=require_remote,
        )
        channel_config = self._channel_by_platform(channel)
        live_channel = channel_config["status"] == "configured"
        return {
            "requested_adapter": requested_adapter,
            "adapter": adapter,
            "adapter_protocol": "internal" if adapter == "fake" else "ACP/A2A",
            "execution_unit_id": unit["unit_id"],
            "execution_unit_kind": unit["kind"],
            "strategy": strategy,
            "orchestration": "serial-dag"
            if strategy == "orchestrator-workers"
            else "single-step",
            "channel": channel,
            "channel_status": channel_config["status"],
            "delivery": {
                "mode": "in-app" if live_channel else "outbound-reserved",
                "requires_connector": not live_channel,
                "ack_event": "channel.delivery.queued",
            },
            "reason": self._dispatch_reason(requested_adapter, adapter, unit, channel_config),
        }

    def _select_execution_unit(
        self,
        adapter: str,
        *,
        execution_unit_id: str | None = None,
        require_remote: bool = False,
    ) -> dict[str, Any]:
        active_units = [
            unit
            for unit in self.execution_units()
            if unit["status"] == "active" and self._execution_unit_available(unit)
        ]
        if execution_unit_id:
            unit = next(
                (item for item in active_units if item["unit_id"] == execution_unit_id),
                None,
            )
            if unit is None:
                raise RuntimeError(
                    f"execution unit {execution_unit_id} is not active or available"
                )
            features = set(unit.get("features") or [])
            if require_remote and not (
                unit.get("kind") == "remote-worker" or "remote-worker" in features
            ):
                raise ValueError(
                    "real repository tasks require an explicit remote worker"
                )
            if adapter not in unit["adapters"]:
                raise RuntimeError(
                    f"execution unit {execution_unit_id} cannot run adapter {adapter}"
                )
            return unit
        for unit in active_units:
            if adapter in unit["adapters"]:
                return unit
        raise RuntimeError(f"no active execution unit can run adapter {adapter}")

    def _execution_unit_available(self, unit: dict[str, Any]) -> bool:
        if unit.get("kind") != "remote-worker" and "remote-worker" not in set(
            unit.get("features") or []
        ):
            return True
        try:
            heartbeat = datetime.fromisoformat(
                str(unit["heartbeat_at"]).replace("Z", "+00:00")
            )
        except (KeyError, TypeError, ValueError):
            return False
        stale_seconds = max(30, int(os.environ.get("V2_WORKER_STALE_SECONDS") or 90))
        return datetime.now(timezone.utc) - heartbeat <= timedelta(seconds=stale_seconds)

    def _channel_by_platform(self, platform: str) -> dict[str, Any]:
        for channel in self.channels():
            if channel["platform"] == platform:
                return channel
        raise RuntimeError(f"channel {platform} is not registered")

    def _channel_config_raw(self, platform: str) -> dict[str, Any]:
        row = self._db.execute(
            "SELECT config_json FROM v2_channels WHERE platform = ?",
            (platform,),
        ).fetchone()
        if row is None:
            return {}
        config = json_loads(row["config_json"])
        return config if isinstance(config, dict) else {}

    def _validate_channel_callback(
        self,
        platform: str,
        config: dict[str, Any],
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> None:
        shared_secret = str(config.get("callback_token") or "").strip()
        if not shared_secret:
            return
        normalized_headers = {key.lower(): value for key, value in headers.items()}
        supplied = (
            normalized_headers.get("x-agentflow-channel-token")
            or normalized_headers.get("x-lark-token")
            or normalized_headers.get("x-dingtalk-token")
            or normalized_headers.get("x-wecom-token")
            or str(payload.get("token") or "")
        )
        if supplied != shared_secret:
            raise PermissionError(f"{platform} callback token mismatch")

    def _record_channel_message(
        self,
        *,
        platform: str,
        direction: str,
        status: str,
        task_id: str | None,
        external_message_id: Any,
        sender: dict[str, Any],
        content: dict[str, Any],
        raw: dict[str, Any],
        error: str | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        message_id = f"chmsg_{uuid4().hex}"
        with self._lock:
            self._db.execute(
                """
                INSERT INTO v2_channel_messages (
                    message_id, channel_id, platform, direction, status,
                    external_message_id, sender_json, content_json, raw_json,
                    task_id, error, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message_id,
                    f"channel_{platform}",
                    platform,
                    direction,
                    status,
                    str(external_message_id or ""),
                    json_dumps(sender),
                    json_dumps(content),
                    json_dumps(raw),
                    task_id,
                    error,
                    now,
                    now,
                ),
            )
            self._db.commit()
        return {
            "message_id": message_id,
            "channel_id": f"channel_{platform}",
            "platform": platform,
            "direction": direction,
            "status": status,
            "external_message_id": str(external_message_id or ""),
            "sender": sender,
            "content": content,
            "raw": raw,
            "task_id": task_id,
            "error": error,
            "created_at": now,
            "updated_at": now,
        }

    def _post_channel_webhook(self, webhook_url: str, payload: dict[str, Any]) -> None:
        data = json_dumps(payload).encode("utf-8")
        webhook_request = request.Request(
            webhook_url,
            data=data,
            method="POST",
            headers={"content-type": "application/json; charset=utf-8"},
        )
        try:
            with request.urlopen(webhook_request, timeout=5) as response:
                status = int(getattr(response, "status", 200))
                if status >= 400:
                    raise RuntimeError(f"webhook returned HTTP {status}")
        except URLError as exc:
            raise RuntimeError(str(exc)) from exc

    def _dispatch_reason(
        self,
        requested_adapter: str,
        adapter: str,
        unit: dict[str, Any],
        channel: dict[str, Any],
    ) -> str:
        if requested_adapter == "auto":
            return f"auto selected {adapter} on {unit['unit_id']} for {channel['platform']}"
        return f"requested {adapter} on {unit['unit_id']} for {channel['platform']}"

    def _run_task(self, task_id: str) -> None:
        try:
            with self._lock:
                row = self._task_row(task_id)
                if row is None or row["status"] in TERMINAL_TASK_STATUSES:
                    return
                self._set_task_status_locked(task_id, "running")
                self._set_workflow_status_locked(task_id, "running")
                self._append_event_locked(
                    task_id,
                    "task.started",
                    "orchestrator",
                    {"runner": "local-sqlite-runner"},
                )
                self._db.commit()

            for agent in self._agent_tasks(task_id):
                if agent["status"] == "completed":
                    continue
                with self._lock:
                    if self._task_row(task_id)["status"] == "cancelled":
                        return
                    started_at = utc_now()
                    step_id = self._start_workflow_step_locked(task_id, agent, started_at)
                    self._transition_agent_status_locked(
                        agent["agent_task_id"], "running", started_at=started_at
                    )
                    self._append_event_locked(
                        task_id,
                        "agent_task.started",
                        agent["role"],
                        {
                            "agent_task_id": agent["agent_task_id"],
                            "title": agent["title"],
                            "adapter": agent["adapter"],
                        },
                    )
                    self._db.commit()
                time.sleep(0.05)
                adapter_result = self._execute_agent_adapter(task_id, agent)
                with self._lock:
                    if self._task_row(task_id)["status"] == "cancelled":
                        return
                    self._append_event_locked(
                        task_id,
                        "agent.message",
                        agent["role"],
                        {
                            "agent_task_id": agent["agent_task_id"],
                            "message": adapter_result["message"],
                            "protocol": adapter_result["protocol"],
                            "execution_mode": adapter_result["execution_mode"],
                        },
                    )
                    result = {
                        "final_summary": adapter_result["summary"],
                        "quality": "contract-passed",
                        "adapter": adapter_result,
                    }
                    artifact = self._write_artifact_locked(
                        task_id,
                        agent["agent_task_id"],
                        "final_summary",
                        "summary",
                        result,
                    )
                    evaluation = self._write_evaluation_locked(
                        task_id,
                        agent["agent_task_id"],
                        "contract",
                        "passed",
                        {"checks": ["non_empty_summary"], "artifact_id": artifact["artifact_id"]},
                    )
                    completed_at = utc_now()
                    self._transition_agent_status_locked(
                        agent["agent_task_id"],
                        "completed",
                        result=result,
                        completed_at=completed_at,
                    )
                    self._append_event_locked(
                        task_id,
                        "agent_task.completed",
                        agent["role"],
                        {
                            "agent_task_id": agent["agent_task_id"],
                            "result": result,
                            "artifact_id": artifact["artifact_id"],
                            "evaluation_id": evaluation["evaluation_id"],
                        },
                    )
                    self._complete_workflow_step_locked(
                        step_id,
                        "completed",
                        {"artifact_id": artifact["artifact_id"]},
                        completed_at,
                    )
                    self._db.commit()

            with self._lock:
                self._set_task_status_locked(task_id, "completed")
                self._set_workflow_status_locked(task_id, "completed")
                self._append_event_locked(
                    task_id,
                    "artifact.created",
                    "artifact-service",
                    {
                        "name": "final_summary",
                        "kind": "summary",
                        "status": "available",
                    },
                )
                self._append_event_locked(
                    task_id,
                    "task.completed",
                    "orchestrator",
                    {"summary": "Task completed and evaluated successfully."},
                )
                self._db.commit()
        except Exception as exc:  # pragma: no cover - defensive safety net
            with self._lock:
                task_row = self._task_row(task_id)
                if task_row is not None and task_row["status"] != "cancelled":
                    failure = failure_summary(exc)
                    self._set_task_status_locked(task_id, "failed")
                    self._set_workflow_status_locked(task_id, "failed")
                    self._append_event_locked(
                        task_id,
                        "task.failed",
                        "orchestrator",
                        {"error": str(exc), "failure_summary": failure},
                    )
                    self._db.commit()

    def _create_workflow_run_locked(
        self,
        task_id: str,
        plan: dict[str, Any],
        now: str,
    ) -> None:
        self._db.execute(
            """
            INSERT INTO v2_workflow_runs (
                workflow_run_id, task_id, status, engine, config_json, attempt,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"wfr_{uuid4().hex}",
                task_id,
                "queued",
                self.workflow_engine_status()["active_engine"],
                json_dumps(
                    {
                        "strategy": plan["strategy"],
                        "graph": plan["graph"],
                        "retry_policy": {
                            "max_attempts": 2,
                            "backoff_seconds": 0.1,
                        },
                        "durable_target": self.workflow_engine_status()["active_engine"],
                    }
                ),
                1,
                now,
                now,
            ),
        )

    def _workflow_run(self, task_id: str) -> Any | None:
        return self._db.execute(
            """
            SELECT * FROM v2_workflow_runs
            WHERE task_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (task_id,),
        ).fetchone()

    def _set_workflow_status_locked(self, task_id: str, status: str) -> None:
        self._db.execute(
            """
            UPDATE v2_workflow_runs
            SET status = ?, updated_at = ?
            WHERE task_id = ?
            """,
            (status, utc_now(), task_id),
        )

    def _start_workflow_step_locked(
        self,
        task_id: str,
        agent: dict[str, Any],
        started_at: str,
    ) -> str:
        run = self._workflow_run(task_id)
        workflow_run_id = run["workflow_run_id"] if run is not None else ""
        step_id = f"wfs_{uuid4().hex}"
        self._db.execute(
            """
            INSERT INTO v2_workflow_steps (
                step_id, workflow_run_id, task_id, agent_task_id, role, status,
                adapter, order_index, input_json, output_json, created_at,
                updated_at, started_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                step_id,
                workflow_run_id,
                task_id,
                agent["agent_task_id"],
                agent["role"],
                "running",
                agent["adapter"],
                agent["order_index"],
                json_dumps(
                    {
                        "goal": agent["goal"],
                        "depends_on": agent["depends_on"],
                        "artifact_contract": agent["artifact_contract"],
                    }
                ),
                json_dumps({}),
                started_at,
                started_at,
                started_at,
            ),
        )
        return step_id

    def _complete_workflow_step_locked(
        self,
        step_id: str,
        status: str,
        output: dict[str, Any],
        completed_at: str,
    ) -> None:
        self._db.execute(
            """
            UPDATE v2_workflow_steps
            SET status = ?, output_json = ?, updated_at = ?, completed_at = ?
            WHERE step_id = ?
            """,
            (status, json_dumps(output), completed_at, completed_at, step_id),
        )

    def _write_artifact_locked(
        self,
        task_id: str,
        agent_task_id: str,
        name: str,
        kind: str,
        content: dict[str, Any],
    ) -> dict[str, Any]:
        artifact_id = f"artifact_{uuid4().hex}"
        now = utc_now()
        ref = f"v2/{task_id}/{artifact_id}.json"
        self._db.execute(
            """
            INSERT INTO v2_artifacts (
                artifact_id, task_id, agent_task_id, name, kind, status,
                content_json, ref, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                artifact_id,
                task_id,
                agent_task_id,
                name,
                kind,
                "available",
                json_dumps(content),
                ref,
                now,
                now,
            ),
        )
        return {
            "artifact_id": artifact_id,
            "task_id": task_id,
            "agent_task_id": agent_task_id,
            "name": name,
            "kind": kind,
            "status": "available",
            "ref": ref,
            "created_at": now,
            "updated_at": now,
        }

    def _write_evaluation_locked(
        self,
        task_id: str,
        agent_task_id: str,
        kind: str,
        status: str,
        details: dict[str, Any],
    ) -> dict[str, Any]:
        evaluation_id = f"eval_{uuid4().hex}"
        now = utc_now()
        self._db.execute(
            """
            INSERT INTO v2_evaluations (
                evaluation_id, task_id, agent_task_id, kind, status,
                details_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                evaluation_id,
                task_id,
                agent_task_id,
                kind,
                status,
                json_dumps(details),
                now,
                now,
            ),
        )
        return {
            "evaluation_id": evaluation_id,
            "task_id": task_id,
            "agent_task_id": agent_task_id,
            "kind": kind,
            "status": status,
            "details": details,
            "created_at": now,
            "updated_at": now,
        }

    def _execute_agent_adapter(
        self,
        task_id: str,
        agent: dict[str, Any],
    ) -> dict[str, Any]:
        adapter = str(agent["adapter"])
        protocol = "internal" if adapter == "fake" else "ACP/A2A"
        follow_up_messages = [
            str(event["payload"].get("message") or "")
            for event in self.events(task_id)
            if event["type"] == "user.message"
            and str(event["payload"].get("message") or "").strip()
        ]
        envelope = {
            "protocol": "agentflow-v2-acp-a2a",
            "protocol_version": "2026-07",
            "task_id": task_id,
            "agent_task_id": agent["agent_task_id"],
            "role": agent["role"],
            "adapter": adapter,
            "goal": agent["goal"],
            "context": {
                "depends_on": agent["depends_on"],
                "artifact_contract": agent["artifact_contract"],
                "follow_up_messages": follow_up_messages,
            },
        }
        if adapter == "fake":
            result = simulated_adapter_result(adapter, protocol, envelope)
            result["execution_mode"] = "fake"
            return result

        command_env = {
            "qwen": "V2_QWEN_CODE_COMMAND",
            "codex": "V2_CODEX_CLI_COMMAND",
            "claude": "V2_CLAUDE_CODE_COMMAND",
            "opencode": "V2_OPENCODE_COMMAND",
        }[adapter]
        default_command = {
            "qwen": "qwen",
            "codex": "codex exec -",
            "claude": "claude -p",
            "opencode": "opencode run",
        }[adapter]
        configured_command = os.environ.get(command_env)
        command = shlex.split(configured_command or default_command)
        executable = shutil.which(command[0]) if command else None
        real_cli_enabled = os.environ.get("V2_ENABLE_REAL_CLI_ADAPTERS") == "1"
        if not real_cli_enabled or executable is None:
            result = simulated_adapter_result(adapter, protocol, envelope)
            result.update(
                {
                    "execution_mode": "protocol-simulated",
                    "command_configured": executable is not None,
                    "requires_env": command_env if executable is None else None,
                    "real_cli_enabled": real_cli_enabled,
                }
            )
            return result

        timed_out = threading.Event()
        process: subprocess.Popen[str] | None = None

        def stop_timed_out_process() -> None:
            timed_out.set()
            if process is not None and process.poll() is None:
                process.kill()

        try:
            process = subprocess.Popen(
                [executable, *command[1:]],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                cwd=self.root,
            )
            timer = threading.Timer(20, stop_timed_out_process)
            timer.daemon = True
            timer.start()
            assert process.stdin is not None
            assert process.stdout is not None
            process.stdin.write(json_dumps(envelope))
            process.stdin.close()
            output_chunks: list[str] = []
            for raw_line in process.stdout:
                line = raw_line.rstrip()
                if not line:
                    continue
                output_chunks.append(line)
                with self._lock:
                    self._append_event_locked(
                        task_id,
                        "agent.message",
                        str(agent["role"]),
                        {
                            "agent_task_id": agent["agent_task_id"],
                            "message": line[:800],
                            "protocol": protocol,
                            "execution_mode": "real-cli",
                            "partial": True,
                        },
                    )
                    self._db.commit()
            process.stdout.close()
            return_code = process.wait()
            timer.cancel()
            if timed_out.is_set():
                raise subprocess.TimeoutExpired(command, 20)
        except (OSError, subprocess.TimeoutExpired) as exc:
            result = simulated_adapter_result(adapter, protocol, envelope)
            result.update({"execution_mode": "cli-error", "error": str(exc)})
            return result
        finally:
            if "timer" in locals():
                timer.cancel()

        output = "\n".join(output_chunks).strip()
        output = output or f"{adapter} completed with code {return_code}"
        if return_code != 0:
            raise RuntimeError(
                f"{adapter} CLI exited with code {return_code}: {output[:400]}"
            )
        return {
            "adapter": adapter,
            "protocol": protocol,
            "execution_mode": "real-cli",
            "exit_code": return_code,
            "message": output[:800],
            "summary": output[:1200],
            "envelope": envelope,
        }

    def _ensure_runner(self, task_id: str) -> None:
        with self._lock:
            if self._closed:
                return
            if self._task_uses_remote_unit(task_id):
                return
            thread = self._threads.get(task_id)
            if thread and thread.is_alive():
                return
            row = self._task_row(task_id)
            if row is None or row["status"] in TERMINAL_TASK_STATUSES:
                return
            target = (
                self._dispatch_temporal_task
                if self.workflow_engine_status()["active_engine"] == "temporal"
                else self._run_task
            )
            thread = threading.Thread(
                target=target,
                args=(task_id,),
                name=f"v2-task-runner-{task_id}",
                daemon=True,
            )
            self._threads[task_id] = thread
            thread.start()

    def close(self, timeout: float = 2.0) -> None:
        with self._lock:
            if self._db_closed:
                return
            self._closed = True
            threads = list(self._threads.values())
        current = threading.current_thread()
        deadline = time.monotonic() + max(0.0, timeout)
        for thread in threads:
            if thread is current or not thread.is_alive():
                continue
            thread.join(timeout=max(0.0, deadline - time.monotonic()))
        if any(thread.is_alive() for thread in threads):
            return
        with self._lock:
            if not self._db_closed:
                self._db.close()
                self._db_closed = True

    def _dispatch_temporal_task(self, task_id: str) -> None:
        try:
            from .temporal_bridge import start_task_workflow

            workflow_id = asyncio.run(start_task_workflow(task_id))
            with self._lock:
                self._append_event_locked(
                    task_id,
                    "workflow.temporal_dispatched",
                    "orchestrator",
                    {
                        "workflow_id": workflow_id,
                        "task_queue": os.environ.get("TEMPORAL_TASK_QUEUE")
                        or "agentflow-v2",
                    },
                )
                self._db.commit()
        except Exception as exc:
            with self._lock:
                if self._task_row(task_id) is None:
                    return
                failure = failure_summary(exc)
                self._set_task_status_locked(task_id, "failed")
                self._set_workflow_status_locked(task_id, "failed")
                self._append_event_locked(
                    task_id,
                    "workflow.temporal_dispatch_failed",
                    "orchestrator",
                    {"error": str(exc), "failure_summary": failure},
                )
                self._append_event_locked(
                    task_id,
                    "task.failed",
                    "orchestrator",
                    {"error": str(exc), "failure_summary": failure},
                )
                self._db.commit()

    def execute_task_now(self, task_id: str) -> dict[str, Any]:
        if self._task_row(task_id) is None:
            raise KeyError(task_id)
        self._run_task(task_id)
        return self.get_task(task_id)

    def _recover_open_tasks(self) -> None:
        rows = self._db.execute(
            """
            SELECT task_id FROM v2_tasks
            WHERE status NOT IN ('completed', 'failed', 'cancelled')
            """
        ).fetchall()
        for row in rows:
            if not self._task_uses_remote_unit(row["task_id"]):
                self._ensure_runner(row["task_id"])

    def _task_uses_remote_unit(self, task_id: str) -> bool:
        row = self._task_row(task_id)
        if row is None:
            return False
        metadata = json_loads(row["metadata_json"])
        dispatch = metadata.get("dispatch") if isinstance(metadata, dict) else None
        unit_id = dispatch.get("execution_unit_id") if isinstance(dispatch, dict) else None
        if not isinstance(unit_id, str):
            return False
        unit = self._db.execute(
            "SELECT * FROM v2_execution_units WHERE unit_id = ?",
            (unit_id,),
        ).fetchone()
        if unit is None:
            return False
        features = set(json_loads(unit["features_json"]))
        return "remote-worker" in features or unit["kind"] == "remote-worker"

    def _queued_remote_agents_locked(self, worker_id: str) -> list[dict[str, Any]]:
        rows = self._db.execute(
            f"""
            SELECT a.* FROM v2_agent_tasks a
            JOIN v2_tasks t ON t.task_id = a.task_id
            WHERE a.status = 'queued' AND t.status IN ('queued', 'running')
            ORDER BY t.created_at ASC, a.order_index ASC
            {self._db.for_update_skip_locked()}
            """
        ).fetchall()
        agents = []
        for row in rows:
            task = self._task_row(row["task_id"])
            metadata = json_loads(task["metadata_json"]) if task is not None else {}
            dispatch = metadata.get("dispatch") if isinstance(metadata, dict) else {}
            selected_unit_id = (
                dispatch.get("execution_unit_id") if isinstance(dispatch, dict) else None
            )
            selected_unit = next(
                (
                    unit
                    for unit in self.execution_units()
                    if unit["unit_id"] == selected_unit_id
                ),
                None,
            )
            workspace = metadata.get("workspace") if isinstance(metadata, dict) else None
            if selected_unit_id == worker_id or (
                not workspace
                and selected_unit is not None
                and not self._execution_unit_available(selected_unit)
            ):
                agents.append(agent_task_from_row(row))
        return agents

    def _dependencies_completed_locked(self, agent: dict[str, Any]) -> bool:
        for role in agent.get("depends_on") or []:
            row = self._db.execute(
                "SELECT status FROM v2_agent_tasks WHERE task_id = ? AND role = ?",
                (agent["task_id"], role),
            ).fetchone()
            if row is None or row["status"] != "completed":
                return False
        return True

    def _agent_task_row(self, agent_task_id: str) -> dict[str, Any]:
        row = self._db.execute(
            "SELECT * FROM v2_agent_tasks WHERE agent_task_id = ?",
            (agent_task_id,),
        ).fetchone()
        if row is None:
            raise KeyError(agent_task_id)
        return agent_task_from_row(row)

    def _require_agent_lease_locked(
        self,
        worker_id: str,
        agent_task_id: str,
        token: str,
        *,
        allowed_statuses: set[str] | None = None,
    ) -> Any:
        row = self._db.execute(
            """
            SELECT * FROM v2_agent_leases
            WHERE agent_task_id = ? AND worker_id = ?
            """,
            (agent_task_id, worker_id),
        ).fetchone()
        statuses = allowed_statuses or {"active"}
        if (
            row is None
            or row["status"] not in statuses
            or not token
            or not secrets.compare_digest(row["lease_hash"], secret_hash(token))
        ):
            raise PermissionError("invalid or expired agent lease")
        if row["status"] == "active" and row["expires_at"] <= utc_now():
            raise PermissionError("agent lease expired")
        return row

    def _extend_worker_leases_locked(self, worker_id: str, ttl_seconds: int) -> None:
        self._db.execute(
            """
            UPDATE v2_agent_leases SET expires_at = ?, updated_at = ?
            WHERE worker_id = ? AND status = 'active'
            """,
            (lease_expiry(max(15, min(ttl_seconds, 600))), utc_now(), worker_id),
        )

    def _reclaim_expired_agent_leases_locked(self) -> None:
        rows = self._db.execute(
            "SELECT * FROM v2_agent_leases WHERE status = 'active' AND expires_at <= ?",
            (utc_now(),),
        ).fetchall()
        for lease in rows:
            expired_at = utc_now()
            next_status = "queued" if int(lease["attempt"]) < 2 else "failed"
            self._transition_agent_status_locked(
                lease["agent_task_id"], next_status
            )
            self._db.execute(
                """
                UPDATE v2_agent_leases SET status = 'expired', updated_at = ?
                WHERE agent_task_id = ?
                """,
                (expired_at, lease["agent_task_id"]),
            )
            self._db.execute(
                """
                UPDATE v2_workflow_steps
                SET status = 'failed', output_json = ?, completed_at = ?, updated_at = ?
                WHERE task_id = ? AND agent_task_id = ? AND status = 'running'
                """,
                (
                    json_dumps(
                        {
                            "error": "worker lease expired",
                            "retrying": next_status == "queued",
                        }
                    ),
                    expired_at,
                    expired_at,
                    lease["task_id"],
                    lease["agent_task_id"],
                ),
            )
            self._append_event_locked(
                lease["task_id"],
                "agent_task.lease_expired",
                "scheduler",
                {
                    "agent_task_id": lease["agent_task_id"],
                    "worker_id": lease["worker_id"],
                    "retrying": next_status == "queued",
                },
            )
            if next_status == "failed":
                self._set_task_status_locked(lease["task_id"], "failed")
                self._set_workflow_status_locked(lease["task_id"], "failed")

    def _finish_remote_step_locked(
        self,
        task_id: str,
        agent_task_id: str,
        status: str,
        output: dict[str, Any],
        completed_at: str,
    ) -> None:
        row = self._db.execute(
            """
            SELECT step_id FROM v2_workflow_steps
            WHERE task_id = ? AND agent_task_id = ? AND status = 'running'
            ORDER BY created_at DESC LIMIT 1
            """,
            (task_id, agent_task_id),
        ).fetchone()
        if row is not None:
            self._complete_workflow_step_locked(row["step_id"], status, output, completed_at)

    def _complete_task_if_ready_locked(self, task_id: str) -> None:
        pending = self._db.execute(
            """
            SELECT COUNT(*) AS count FROM v2_agent_tasks
            WHERE task_id = ? AND status != 'completed'
            """,
            (task_id,),
        ).fetchone()["count"]
        if int(pending) != 0:
            return
        self._set_task_status_locked(task_id, "completed")
        self._set_workflow_status_locked(task_id, "completed")
        self._append_event_locked(
            task_id,
            "task.completed",
            "orchestrator",
            {"summary": "Task completed by remote execution unit."},
        )

    def _plan_for_task(self, task_id: str) -> dict[str, Any] | None:
        plan_row = self._db.execute(
            """
            SELECT * FROM v2_plans
            WHERE task_id = ?
            ORDER BY version DESC
            LIMIT 1
            """,
            (task_id,),
        ).fetchone()
        if plan_row is None:
            return None
        plan = dict(plan_row)
        plan["graph"] = json_loads(plan.pop("graph_json"))
        plan["artifact_contract"] = json_loads(plan.pop("artifact_contract_json"))
        plan["agent_tasks"] = self._agent_tasks(task_id)
        return plan

    def _agent_tasks(self, task_id: str) -> list[dict[str, Any]]:
        rows = self._db.execute(
            """
            SELECT * FROM v2_agent_tasks
            WHERE task_id = ?
            ORDER BY order_index ASC
            """,
            (task_id,),
        ).fetchall()
        return [agent_task_from_row(row) for row in rows]

    def _progress(self, task_id: str) -> dict[str, Any]:
        agents = self._agent_tasks(task_id)
        total = len(agents)
        completed = len([agent for agent in agents if agent["status"] == "completed"])
        running = len([agent for agent in agents if agent["status"] == "running"])
        percent = 100 if total == 0 else int((completed / total) * 100)
        return {
            "completed_steps": completed,
            "running_steps": running,
            "total_steps": total,
            "percent": percent,
        }

    def _result(self, task_id: str) -> dict[str, Any] | None:
        row = self._task_row(task_id)
        if row is None or row["status"] not in {"completed", "failed"}:
            return None
        artifacts = self.artifacts(task_id)
        evaluations = self.evaluations(task_id)
        if row["status"] == "failed":
            fallback_failure = {
                "reason": "The task failed before producing a result.",
                "impact": "No final result is available.",
                "next_action": "Retry the task or inspect the audit events.",
                "retryable": True,
            }
            failed_events = [
                event for event in self.events(task_id) if event["type"] == "task.failed"
            ]
            recorded_failure = (
                failed_events[-1]["payload"].get("failure_summary")
                if failed_events
                else None
            )
            failure = dict(fallback_failure)
            if isinstance(recorded_failure, dict):
                failure.update(
                    {
                        key: value
                        for key, value in recorded_failure.items()
                        if value is not None
                    }
                )
            return {
                "summary": failure["reason"],
                "failure": failure,
                "artifacts": artifacts,
                "evaluation": {"status": "failed", "checks": [], "items": evaluations},
            }
        summaries = [
            agent["result"].get("final_summary")
            for agent in self._agent_tasks(task_id)
            if agent["result"].get("final_summary")
        ]
        return {
            "summary": " ".join(summaries) or "Task completed.",
            "artifacts": artifacts,
            "evaluation": {
                "status": "passed"
                if all(item["status"] == "passed" for item in evaluations)
                else "failed",
                "checks": [item["kind"] for item in evaluations] or ["contract"],
                "items": evaluations,
            },
        }

    def _find_task_by_idempotency_key(self, key: str) -> dict[str, Any] | None:
        row = self._db.execute(
            "SELECT task_id FROM v2_tasks WHERE idempotency_key = ?",
            (key,),
        ).fetchone()
        if row is None:
            return None
        return self.get_task(row["task_id"])

    def _task_row(self, task_id: str) -> Any | None:
        return self._db.execute(
            "SELECT * FROM v2_tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()

    def _task_summary_from_row(self, row: Any) -> dict[str, Any]:
        task_id = row["task_id"]
        return {
            "task_id": task_id,
            "tenant_id": row["tenant_id"],
            "project_id": row["project_id"],
            "created_by": row["created_by"],
            "title": row["title"],
            "goal": row["goal"],
            "mode": row["mode"],
            "status": row["status"],
            "priority": row["priority"],
            "channel": row["channel"],
            "adapter": row["adapter"],
            "execution_mode": self._execution_mode(task_id),
            "metadata": json_loads(row["metadata_json"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "progress": self._progress(task_id),
            "plan": self._plan_for_task(task_id),
            "result": self._result(task_id),
        }

    def _execution_mode(self, task_id: str) -> str:
        modes = {
            str(agent["result"].get("adapter", {}).get("execution_mode"))
            for agent in self._agent_tasks(task_id)
            if agent["result"].get("adapter", {}).get("execution_mode")
        }
        if "real-cli" in modes:
            return "real-cli"
        if "protocol-simulated" in modes:
            return "protocol-simulated"
        if "fake" in modes or "simulated" in modes:
            return "fake"
        return "pending"

    def _append_event_locked(
        self,
        task_id: str,
        event_type: str,
        actor: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        sequence = self._next_sequence_locked(task_id)
        event_id = f"v2evt_{uuid4().hex}"
        created_at = utc_now()
        self._db.execute(
            """
            INSERT INTO v2_events (
                event_id, task_id, sequence, type, actor, payload_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                task_id,
                sequence,
                event_type,
                actor,
                json_dumps(payload),
                created_at,
            ),
        )
        self._touch_task_locked(task_id, updated_at=created_at)
        return {
            "event_id": event_id,
            "task_id": task_id,
            "sequence": sequence,
            "type": event_type,
            "actor": actor,
            "payload": payload,
            "created_at": created_at,
        }

    def _next_sequence_locked(self, task_id: str) -> int:
        self._db.task_lock(task_id)
        row = self._db.execute(
            """
            SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence
            FROM v2_events
            WHERE task_id = ?
            """,
            (task_id,),
        ).fetchone()
        return int(row["next_sequence"])

    def _set_task_status_locked(self, task_id: str, status: str) -> None:
        row = self._task_row(task_id)
        if row is None:
            raise KeyError(task_id)
        current = str(row["status"])
        if status == current:
            return
        if status not in TASK_STATUS_TRANSITIONS.get(current, set()):
            raise ValueError(f"invalid task status transition: {current} -> {status}")
        self._db.execute(
            "UPDATE v2_tasks SET status = ?, updated_at = ? WHERE task_id = ?",
            (status, utc_now(), task_id),
        )

    def _transition_agent_status_locked(
        self,
        agent_task_id: str,
        status: str,
        *,
        result: dict[str, Any] | None = None,
        started_at: str | None = None,
        completed_at: str | None = None,
        reset_result: bool = False,
    ) -> None:
        row = self._db.execute(
            "SELECT status FROM v2_agent_tasks WHERE agent_task_id = ?",
            (agent_task_id,),
        ).fetchone()
        if row is None:
            raise KeyError(agent_task_id)
        current = str(row["status"])
        if status != current and status not in AGENT_STATUS_TRANSITIONS.get(current, set()):
            raise ValueError(f"invalid agent status transition: {current} -> {status}")
        now = utc_now()
        if reset_result:
            self._db.execute(
                """
                UPDATE v2_agent_tasks
                SET status = ?, result_json = '{}', completed_at = NULL, updated_at = ?
                WHERE agent_task_id = ?
                """,
                (status, now, agent_task_id),
            )
            return
        self._db.execute(
            """
            UPDATE v2_agent_tasks
            SET status = ?, result_json = COALESCE(?, result_json),
                started_at = COALESCE(started_at, ?),
                completed_at = COALESCE(?, completed_at), updated_at = ?
            WHERE agent_task_id = ?
            """,
            (
                status,
                json_dumps(result) if result is not None else None,
                started_at,
                completed_at,
                now,
                agent_task_id,
            ),
        )

    def _touch_task_locked(self, task_id: str, updated_at: str | None = None) -> None:
        self._db.execute(
            "UPDATE v2_tasks SET updated_at = ? WHERE task_id = ?",
            (updated_at or utc_now(), task_id),
        )

    def _ensure_defaults(self) -> None:
        now = utc_now()
        bootstrap_user = os.environ.get(
            "RUN_MANAGER_BOOTSTRAP_EMAIL", "owner@example.com"
        )
        unit_id = os.environ.get("V2_LOCAL_EXECUTION_UNIT_ID", "local-dev").strip()
        unit_kind = os.environ.get(
            "V2_LOCAL_EXECUTION_UNIT_KIND", "local-workspace"
        ).strip()
        if not unit_id or not unit_kind:
            raise ValueError("local execution unit id and kind must not be empty")
        unit_labels = local_execution_unit_json(
            "V2_LOCAL_EXECUTION_UNIT_LABELS_JSON",
            {"region": "local", "tier": "dev"},
        )
        unit_labels.setdefault("execution_location", "co-located-runtime")
        unit_resources = local_execution_unit_json(
            "V2_LOCAL_EXECUTION_UNIT_RESOURCES_JSON",
            {"cpu": 2, "memory_mb": 2048},
        )
        unit_adapters = comma_list_env(
            "V2_LOCAL_EXECUTION_UNIT_ADAPTERS",
            ["fake", "qwen", "codex", "claude", "opencode"],
        )
        unsupported_adapters = set(unit_adapters) - (SUPPORTED_ADAPTERS - {"auto"})
        if unsupported_adapters:
            names = ", ".join(sorted(unsupported_adapters))
            raise ValueError(f"unsupported local execution unit adapters: {names}")
        unit_features = comma_list_env(
            "V2_LOCAL_EXECUTION_UNIT_FEATURES",
            ["workspace", "artifacts", "events", "cli-adapters"],
        )
        with self._lock:
            self._db.execute(
                """
                INSERT INTO v2_tenants (
                    tenant_id, name, status, settings_json, created_by,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id) DO UPDATE SET updated_at = excluded.updated_at
                """,
                (
                    "tenant_default",
                    "Default Tenant",
                    "active",
                    json_dumps({"plan": "local"}),
                    "system",
                    now,
                    now,
                ),
            )
            self._db.execute(
                """
                INSERT OR IGNORE INTO v2_projects (
                    project_id, tenant_id, name, status, created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "project_default",
                    "tenant_default",
                    "Default Project",
                    "active",
                    bootstrap_user,
                    now,
                    now,
                ),
            )
            self._db.execute(
                """
                INSERT OR IGNORE INTO v2_project_members (
                    project_id, user_id, role, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                ("project_default", bootstrap_user, "owner", "active", now, now),
            )
            for role, permissions in [
                ("owner", ["*"]),
                ("operator", ["tasks:*", "channels:*", "execution_units:*"]),
                ("auditor", ["tasks:read", "events:read", "audit:read"]),
                ("member", ["tasks:create", "tasks:read", "tasks:write"]),
            ]:
                self._db.execute(
                    """
                    INSERT OR IGNORE INTO v2_rbac_policies (
                        tenant_id, role, permissions_json, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    ("tenant_default", role, json_dumps(permissions), now, now),
                )
            self._db.execute(
                """
                INSERT OR IGNORE INTO v2_tenant_users (
                    tenant_id, user_id, email, roles_json, status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "tenant_default",
                    bootstrap_user,
                    bootstrap_user,
                    json_dumps(["owner"]),
                    "active",
                    now,
                    now,
                ),
            )
            if unit_id != "local-dev":
                self._db.execute(
                    """
                    DELETE FROM v2_execution_units
                    WHERE unit_id = ? AND kind = ? AND labels_json = ?
                        AND resources_json = ?
                    """,
                    (
                        "local-dev",
                        "local-workspace",
                        json_dumps({"region": "local", "tier": "dev"}),
                        json_dumps({"cpu": 2, "memory_mb": 2048}),
                    ),
                )
            self._db.execute(
                """
                INSERT INTO v2_execution_units (
                    unit_id, kind, status, labels_json, resources_json,
                    adapters_json, features_json, heartbeat_at, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(unit_id) DO UPDATE SET
                    kind = excluded.kind,
                    status = excluded.status,
                    labels_json = excluded.labels_json,
                    resources_json = excluded.resources_json,
                    adapters_json = excluded.adapters_json,
                    features_json = excluded.features_json,
                    heartbeat_at = excluded.heartbeat_at,
                    updated_at = excluded.updated_at
                """,
                (
                    unit_id,
                    unit_kind,
                    "active",
                    json_dumps(unit_labels),
                    json_dumps(unit_resources),
                    json_dumps(unit_adapters),
                    json_dumps(unit_features),
                    now,
                    now,
                    now,
                ),
            )
            for platform in ["web", "mobile", "dingtalk", "feishu", "wecom"]:
                self._db.execute(
                    """
                    INSERT OR IGNORE INTO v2_channels (
                        channel_id, platform, status, config_json, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"channel_{platform}",
                        platform,
                        "configured" if platform == "web" else "reserved",
                        json_dumps(
                            {
                                "signed_callbacks": platform != "web",
                                "mobile_ready": platform in {"web", "mobile"},
                                "bot_connector": platform
                                if platform in {"dingtalk", "feishu", "wecom"}
                                else None,
                            }
                        ),
                        now,
                        now,
                    ),
                )
            self._db.commit()

    def _init_db(self) -> None:
        with self._lock:
            self._db.executescript(
                """
                CREATE TABLE IF NOT EXISTS v2_tasks (
                    task_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    title TEXT NOT NULL,
                    goal TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    priority TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    adapter TEXT NOT NULL,
                    idempotency_key TEXT UNIQUE,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS v2_projects (
                    project_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS v2_project_members (
                    project_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(project_id, user_id),
                    FOREIGN KEY(project_id) REFERENCES v2_projects(project_id)
                );

                CREATE TABLE IF NOT EXISTS v2_plans (
                    plan_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    strategy TEXT NOT NULL,
                    graph_json TEXT NOT NULL,
                    artifact_contract_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(task_id) REFERENCES v2_tasks(task_id)
                );

                CREATE TABLE IF NOT EXISTS v2_agent_tasks (
                    agent_task_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    plan_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    title TEXT NOT NULL,
                    goal TEXT NOT NULL,
                    status TEXT NOT NULL,
                    adapter TEXT NOT NULL,
                    order_index INTEGER NOT NULL,
                    depends_on_json TEXT NOT NULL,
                    artifact_contract_json TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(task_id) REFERENCES v2_tasks(task_id),
                    FOREIGN KEY(plan_id) REFERENCES v2_plans(plan_id)
                );

                CREATE TABLE IF NOT EXISTS v2_agent_leases (
                    agent_task_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    worker_id TEXT NOT NULL,
                    lease_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempt INTEGER NOT NULL,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(agent_task_id) REFERENCES v2_agent_tasks(agent_task_id),
                    FOREIGN KEY(task_id) REFERENCES v2_tasks(task_id)
                );

                CREATE TABLE IF NOT EXISTS v2_permissions (
                    permission_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    agent_task_id TEXT NOT NULL,
                    worker_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    decision_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    delivered_at TEXT,
                    FOREIGN KEY(task_id) REFERENCES v2_tasks(task_id),
                    FOREIGN KEY(agent_task_id) REFERENCES v2_agent_tasks(agent_task_id)
                );

                CREATE TABLE IF NOT EXISTS v2_events (
                    event_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    type TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(task_id, sequence),
                    FOREIGN KEY(task_id) REFERENCES v2_tasks(task_id)
                );

                CREATE TABLE IF NOT EXISTS v2_event_dedup (
                    task_id TEXT NOT NULL,
                    agent_task_id TEXT NOT NULL,
                    attempt INTEGER NOT NULL,
                    source_event_id TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(task_id, agent_task_id, attempt, source_event_id),
                    FOREIGN KEY(task_id) REFERENCES v2_tasks(task_id),
                    FOREIGN KEY(agent_task_id) REFERENCES v2_agent_tasks(agent_task_id),
                    FOREIGN KEY(event_id) REFERENCES v2_events(event_id)
                );

                CREATE TABLE IF NOT EXISTS v2_execution_units (
                    unit_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    labels_json TEXT NOT NULL,
                    resources_json TEXT NOT NULL,
                    adapters_json TEXT NOT NULL,
                    features_json TEXT NOT NULL,
                    heartbeat_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS v2_channels (
                    channel_id TEXT PRIMARY KEY,
                    platform TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    config_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS v2_channel_messages (
                    message_id TEXT PRIMARY KEY,
                    channel_id TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    status TEXT NOT NULL,
                    external_message_id TEXT NOT NULL,
                    sender_json TEXT NOT NULL,
                    content_json TEXT NOT NULL,
                    raw_json TEXT NOT NULL,
                    task_id TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS v2_tenants (
                    tenant_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    settings_json TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS v2_tenant_users (
                    tenant_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    email TEXT NOT NULL,
                    roles_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(tenant_id, user_id)
                );

                CREATE TABLE IF NOT EXISTS v2_rbac_policies (
                    tenant_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    permissions_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(tenant_id, role)
                );

                CREATE TABLE IF NOT EXISTS v2_workflow_runs (
                    workflow_run_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    engine TEXT NOT NULL,
                    config_json TEXT NOT NULL,
                    attempt INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(task_id) REFERENCES v2_tasks(task_id)
                );

                CREATE TABLE IF NOT EXISTS v2_workflow_steps (
                    step_id TEXT PRIMARY KEY,
                    workflow_run_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    agent_task_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    status TEXT NOT NULL,
                    adapter TEXT NOT NULL,
                    order_index INTEGER NOT NULL,
                    input_json TEXT NOT NULL,
                    output_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    FOREIGN KEY(workflow_run_id) REFERENCES v2_workflow_runs(workflow_run_id),
                    FOREIGN KEY(task_id) REFERENCES v2_tasks(task_id),
                    FOREIGN KEY(agent_task_id) REFERENCES v2_agent_tasks(agent_task_id)
                );

                CREATE TABLE IF NOT EXISTS v2_artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    agent_task_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    content_json TEXT NOT NULL,
                    ref TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(task_id) REFERENCES v2_tasks(task_id),
                    FOREIGN KEY(agent_task_id) REFERENCES v2_agent_tasks(agent_task_id)
                );

                CREATE TABLE IF NOT EXISTS v2_evaluations (
                    evaluation_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    agent_task_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    details_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(task_id) REFERENCES v2_tasks(task_id),
                    FOREIGN KEY(agent_task_id) REFERENCES v2_agent_tasks(agent_task_id)
                );

                CREATE TABLE IF NOT EXISTS v2_replays (
                    replay_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    requested_by TEXT NOT NULL,
                    status TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(task_id) REFERENCES v2_tasks(task_id)
                );

                CREATE INDEX IF NOT EXISTS idx_v2_tasks_status
                    ON v2_tasks(status);
                CREATE INDEX IF NOT EXISTS idx_v2_events_task_sequence
                    ON v2_events(task_id, sequence);
                CREATE INDEX IF NOT EXISTS idx_v2_agent_tasks_task
                    ON v2_agent_tasks(task_id, order_index);
                CREATE INDEX IF NOT EXISTS idx_v2_agent_leases_worker
                    ON v2_agent_leases(worker_id, status, expires_at);
                CREATE INDEX IF NOT EXISTS idx_v2_permissions_worker
                    ON v2_permissions(worker_id, status, updated_at);
                CREATE INDEX IF NOT EXISTS idx_v2_workflow_runs_task
                    ON v2_workflow_runs(task_id);
                CREATE INDEX IF NOT EXISTS idx_v2_workflow_steps_task
                    ON v2_workflow_steps(task_id, order_index);
                CREATE INDEX IF NOT EXISTS idx_v2_artifacts_task
                    ON v2_artifacts(task_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_v2_evaluations_task
                    ON v2_evaluations(task_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_v2_replays_task
                    ON v2_replays(task_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_v2_channel_messages_platform
                    ON v2_channel_messages(platform, created_at);
                CREATE INDEX IF NOT EXISTS idx_v2_tenant_users_tenant
                    ON v2_tenant_users(tenant_id);
                """
            )
            self._db.commit()


def summarize_goal(goal: str) -> str:
    compact = " ".join(goal.split())
    if len(compact) <= 72:
        return compact
    return compact[:69].rstrip() + "..."


def normalize_choice(value: Any, allowed: set[str], default: str) -> str:
    choice = str(value or default).strip().lower()
    return choice if choice in allowed else default


def normalize_workspace_contract(value: Any) -> dict[str, Any]:
    if value is None or value == "":
        return {}
    if isinstance(value, str):
        source_path = value.strip()
        if not source_path:
            return {}
        raise ValueError(
            "workspace must be an object with execution_unit_id and source_path"
        )
    if not isinstance(value, dict):
        raise ValueError("workspace must be a path or object")
    source_path = str(value.get("source_path") or value.get("path") or "").strip()
    if not source_path:
        raise ValueError("workspace.source_path is required")
    execution_unit_id = str(value.get("execution_unit_id") or "").strip()
    if not execution_unit_id:
        raise ValueError("workspace.execution_unit_id is required")
    test_command = value.get("test_command")
    if test_command is not None and not isinstance(test_command, (str, list)):
        raise ValueError("workspace.test_command must be a command string or argv list")
    if isinstance(test_command, list) and not all(
        isinstance(item, str) and item for item in test_command
    ):
        raise ValueError("workspace.test_command argv must contain non-empty strings")
    return {
        "strategy": "git-worktree",
        "execution_unit_id": execution_unit_id,
        "source_path": source_path,
        "ref": str(value.get("ref") or "HEAD").strip(),
        "test_command": test_command,
        "require_changes": bool(value.get("require_changes", True)),
    }


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def json_loads(value: str | None) -> Any:
    if not value:
        return {}
    return json.loads(value)


def secret_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def lease_expiry(ttl_seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)).isoformat(
        timespec="milliseconds"
    )


def simulated_adapter_result(
    adapter: str,
    protocol: str,
    envelope: dict[str, Any],
) -> dict[str, Any]:
    role = str(envelope.get("role") or "agent")
    goal = str(envelope.get("goal") or "complete the assigned task")
    summary = f"{role} completed via {adapter}: {goal}"
    return {
        "adapter": adapter,
        "protocol": protocol,
        "execution_mode": "simulated",
        "message": summary,
        "summary": summary,
        "envelope": envelope,
    }


def failure_summary(exc: Exception) -> dict[str, Any]:
    reason = str(exc).strip() or exc.__class__.__name__
    lowered = reason.lower()
    if "timeout" in lowered:
        impact = "The execution exceeded its time limit and did not finish."
        next_action = "Retry with a smaller scope or increase the execution timeout."
        category = "timeout"
    elif "adapter" in lowered or "command" in lowered or "cli" in lowered:
        impact = "The selected Agent CLI could not complete this task."
        next_action = "Check the execution unit, CLI credentials, and adapter availability."
        category = "adapter"
    elif "permission" in lowered or "forbidden" in lowered:
        impact = "The task stopped before an operation requiring permission."
        next_action = "Review the task permissions and approve or adjust the request."
        category = "permission"
    else:
        impact = "The workflow stopped before producing a complete result."
        next_action = "Retry the task; if it fails again, open the audit bundle for details."
        category = "runtime"
    return {
        "reason": reason,
        "impact": impact,
        "next_action": next_action,
        "category": category,
        "retryable": category != "permission",
    }


def event_from_row(row: Any) -> dict[str, Any]:
    return {
        "event_id": row["event_id"],
        "task_id": row["task_id"],
        "sequence": row["sequence"],
        "type": row["type"],
        "actor": row["actor"],
        "payload": json_loads(row["payload_json"]),
        "created_at": row["created_at"],
    }


def agent_task_from_row(row: Any) -> dict[str, Any]:
    return {
        "agent_task_id": row["agent_task_id"],
        "task_id": row["task_id"],
        "plan_id": row["plan_id"],
        "role": row["role"],
        "title": row["title"],
        "goal": row["goal"],
        "status": row["status"],
        "adapter": row["adapter"],
        "order_index": row["order_index"],
        "depends_on": json_loads(row["depends_on_json"]),
        "artifact_contract": json_loads(row["artifact_contract_json"]),
        "result": json_loads(row["result_json"]),
        "started_at": row["started_at"],
        "completed_at": row["completed_at"],
        "updated_at": row["updated_at"],
    }


def unit_from_row(row: Any) -> dict[str, Any]:
    return {
        "unit_id": row["unit_id"],
        "kind": row["kind"],
        "status": row["status"],
        "labels": json_loads(row["labels_json"]),
        "resources": json_loads(row["resources_json"]),
        "adapters": json_loads(row["adapters_json"]),
        "features": json_loads(row["features_json"]),
        "heartbeat_at": row["heartbeat_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def permission_from_row(row: Any) -> dict[str, Any]:
    return {
        "permission_id": row["permission_id"],
        "task_id": row["task_id"],
        "agent_task_id": row["agent_task_id"],
        "worker_id": row["worker_id"],
        "status": row["status"],
        "request": json_loads(row["request_json"]),
        "decision": json_loads(row["decision_json"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "delivered_at": row["delivered_at"],
    }


def channel_from_row(row: Any) -> dict[str, Any]:
    return {
        "channel_id": row["channel_id"],
        "platform": row["platform"],
        "status": row["status"],
        "config": redact_secret_config(json_loads(row["config_json"])),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def channel_message_from_row(row: Any) -> dict[str, Any]:
    return {
        "message_id": row["message_id"],
        "channel_id": row["channel_id"],
        "platform": row["platform"],
        "direction": row["direction"],
        "status": row["status"],
        "external_message_id": row["external_message_id"],
        "sender": json_loads(row["sender_json"]),
        "content": json_loads(row["content_json"]),
        "raw": redact_secret_config(json_loads(row["raw_json"])),
        "task_id": row["task_id"],
        "error": row["error"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def tenant_from_row(row: Any) -> dict[str, Any]:
    return {
        "tenant_id": row["tenant_id"],
        "name": row["name"],
        "status": row["status"],
        "settings": json_loads(row["settings_json"]),
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def project_from_row(row: Any) -> dict[str, Any]:
    return {
        "project_id": row["project_id"],
        "tenant_id": row["tenant_id"],
        "name": row["name"],
        "status": row["status"],
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def project_member_from_row(row: Any) -> dict[str, Any]:
    return {
        "project_id": row["project_id"],
        "user_id": row["user_id"],
        "role": row["role"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def tenant_user_from_row(row: Any) -> dict[str, Any]:
    return {
        "tenant_id": row["tenant_id"],
        "user_id": row["user_id"],
        "email": row["email"],
        "roles": json_loads(row["roles_json"]),
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def rbac_policy_from_row(row: Any) -> dict[str, Any]:
    return {
        "tenant_id": row["tenant_id"],
        "role": row["role"],
        "permissions": json_loads(row["permissions_json"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def workflow_run_from_row(row: Any) -> dict[str, Any]:
    return {
        "workflow_run_id": row["workflow_run_id"],
        "task_id": row["task_id"],
        "status": row["status"],
        "engine": row["engine"],
        "config": json_loads(row["config_json"]),
        "attempt": row["attempt"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def workflow_step_from_row(row: Any) -> dict[str, Any]:
    return {
        "step_id": row["step_id"],
        "workflow_run_id": row["workflow_run_id"],
        "task_id": row["task_id"],
        "agent_task_id": row["agent_task_id"],
        "role": row["role"],
        "status": row["status"],
        "adapter": row["adapter"],
        "order_index": row["order_index"],
        "input": json_loads(row["input_json"]),
        "output": json_loads(row["output_json"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "started_at": row["started_at"],
        "completed_at": row["completed_at"],
    }


def artifact_from_row(row: Any) -> dict[str, Any]:
    return {
        "artifact_id": row["artifact_id"],
        "task_id": row["task_id"],
        "agent_task_id": row["agent_task_id"],
        "name": row["name"],
        "kind": row["kind"],
        "status": row["status"],
        "content": json_loads(row["content_json"]),
        "ref": row["ref"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def evaluation_from_row(row: Any) -> dict[str, Any]:
    return {
        "evaluation_id": row["evaluation_id"],
        "task_id": row["task_id"],
        "agent_task_id": row["agent_task_id"],
        "kind": row["kind"],
        "status": row["status"],
        "details": json_loads(row["details_json"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def replay_from_row(row: Any) -> dict[str, Any]:
    return {
        "replay_id": row["replay_id"],
        "task_id": row["task_id"],
        "requested_by": row["requested_by"],
        "status": row["status"],
        "snapshot": json_loads(row["snapshot_json"]),
        "created_at": row["created_at"],
    }


def redact_secret_config(value: Any) -> Any:
    secret_keys = {
        "api_key",
        "apikey",
        "authorization",
        "cookie",
        "password",
        "private_key",
        "secret",
        "session_secret",
        "token",
        "app_secret",
        "signing_secret",
        "callback_token",
        "webhook_url",
    }
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            if key.lower() in secret_keys and item:
                redacted[key] = "<configured>"
            else:
                redacted[key] = redact_secret_config(item)
        return redacted
    if isinstance(value, list):
        return [redact_secret_config(item) for item in value]
    return value


def normalize_inbound_channel_payload(platform: str, payload: dict[str, Any]) -> dict[str, Any]:
    if platform == "dingtalk":
        sender = {
            "sender_id": payload.get("senderStaffId") or payload.get("senderId"),
            "conversation_id": payload.get("conversationId"),
        }
        return {
            "text": nested_text(payload, ["text", "content"])
            or payload.get("content")
            or payload.get("message"),
            "sender": sender,
            "external_message_id": payload.get("msgId") or payload.get("messageId"),
            "idempotency_key": payload.get("msgId"),
            "tenant_id": payload.get("tenant_id"),
        }
    if platform == "feishu":
        event = payload.get("event") if isinstance(payload.get("event"), dict) else payload
        message = event.get("message") if isinstance(event.get("message"), dict) else event
        sender = event.get("sender") if isinstance(event.get("sender"), dict) else {}
        return {
            "text": extract_feishu_text(message),
            "sender": sender,
            "external_message_id": message.get("message_id") or event.get("message_id"),
            "idempotency_key": message.get("message_id") or event.get("message_id"),
            "tenant_id": payload.get("tenant_id") or event.get("tenant_id"),
        }
    if platform == "wecom":
        sender = {
            "from_user": payload.get("FromUserName"),
            "agent_id": payload.get("AgentID"),
        }
        return {
            "text": payload.get("Content") or payload.get("content") or payload.get("message"),
            "sender": sender,
            "external_message_id": payload.get("MsgId") or payload.get("msgid"),
            "idempotency_key": payload.get("MsgId") or payload.get("msgid"),
            "tenant_id": payload.get("tenant_id"),
        }
    return {
        "text": payload.get("text") or payload.get("message") or payload.get("goal"),
        "sender": payload.get("sender") or {},
        "external_message_id": payload.get("message_id"),
        "idempotency_key": payload.get("message_id"),
        "tenant_id": payload.get("tenant_id"),
    }


def nested_text(payload: dict[str, Any], path: list[str]) -> str | None:
    current: Any = payload
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current if isinstance(current, str) else None


def extract_feishu_text(message: dict[str, Any]) -> str | None:
    content = message.get("content")
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return content
        if isinstance(parsed, dict):
            text = parsed.get("text")
            return text if isinstance(text, str) else content
        return content
    if isinstance(content, dict):
        text = content.get("text")
        return text if isinstance(text, str) else None
    text = message.get("text")
    return text if isinstance(text, str) else None


def outbound_channel_payload(platform: str, text: str) -> dict[str, Any]:
    if platform == "feishu":
        return {"msg_type": "text", "content": {"text": text}}
    return {"msgtype": "text", "text": {"content": text}}


def v2_event_to_daemon_event(event: dict[str, Any]) -> dict[str, Any]:
    payload = event["payload"]
    event_type = event["type"]
    if event_type == "adapter.daemon_event":
        native = payload.get("event")
        if isinstance(native, dict):
            projected = dict(native)
            projected["id"] = event["sequence"]
            projected["v"] = int(projected.get("v") or 1)
            projected["_meta"] = {
                **dict(projected.get("_meta") or {}),
                **_v2_daemon_meta(event),
            }
            return projected
    if event_type in {"task.created", "user.message"}:
        update = {
            "sessionUpdate": "user_message_chunk",
            "content": {
                "type": "text",
                "text": str(payload.get("message") or payload.get("goal") or ""),
            },
        }
    elif event_type == "agent.message":
        update = {
            "sessionUpdate": "agent_message_chunk",
            "content": {"type": "text", "text": str(payload.get("message") or "")},
        }
    elif event_type == "agent.thought":
        update = {
            "sessionUpdate": "agent_thought_chunk",
            "content": {"type": "text", "text": str(payload.get("message") or "")},
        }
    elif event_type.startswith("tool."):
        status = {
            "tool.started": "in_progress",
            "tool.updated": "in_progress",
            "tool.completed": "completed",
            "tool.failed": "failed",
        }[event_type]
        update: dict[str, Any] = {
            "sessionUpdate": (
                "tool_call" if event_type == "tool.started" else "tool_call_update"
            ),
            "toolCallId": str(payload.get("tool_call_id") or "unknown"),
            "status": status,
        }
        name = str(payload.get("name") or "tool")
        if event_type == "tool.started" or name != "tool":
            update.update(
                {
                    "title": str(payload.get("title") or name),
                    "kind": payload.get("kind") or "tool",
                    "toolName": name,
                }
            )
        if payload.get("input") is not None:
            update["rawInput"] = payload["input"]
        if payload.get("output") is not None:
            update["rawOutput"] = payload["output"]
        if payload.get("kind") in {"mcp", "subagent"}:
            update["provenance"] = payload["kind"]
        if payload.get("parent_tool_call_id"):
            update["parentToolCallId"] = payload["parent_tool_call_id"]
        if payload.get("subagent_type"):
            update["subagentType"] = payload["subagent_type"]
    elif event_type == "shell.output":
        return _v2_daemon_event(
            event,
            "shell_output",
            {
                "output": str(payload.get("output") or ""),
                "stream": payload.get("stream") or "stdout",
                "source": payload.get("source") or "agent",
            },
        )
    elif event_type == "agent.status":
        update = {
            "sessionUpdate": "agent_message_chunk",
            "content": {"type": "text", "text": ""},
            "_meta": {"status": payload.get("status"), "usage": payload.get("usage")},
        }
    elif event_type == "task.completed":
        return _v2_daemon_event(
            event,
            "turn_complete",
            {
                "stopReason": "end_turn",
                "summary": str(payload.get("summary") or "Done"),
            },
        )
    elif event_type in {"task.failed", "agent_task.failed"}:
        return _v2_daemon_event(
            event,
            "turn_error",
            {"message": str(payload.get("error") or payload.get("reason") or "Task failed")},
        )
    elif event_type == "task.cancelled":
        return _v2_daemon_event(
            event,
            "prompt_cancelled",
            {"reason": str(payload.get("reason") or "Cancelled")},
        )
    elif event_type == "permission.requested":
        return _v2_daemon_event(
            event,
            "permission_request",
            {
                "requestId": payload.get("permission_id"),
                "sessionId": payload.get("agent_task_id"),
                "toolCall": {
                    "name": payload.get("tool") or "Tool",
                    "input": payload.get("context") or {},
                },
                "options": [
                    {"optionId": "allow_once", "label": "Allow once"},
                    {"optionId": "deny", "label": "Deny"},
                ],
            },
        )
    elif event_type == "permission.resolved":
        return _v2_daemon_event(
            event,
            "permission_resolved",
            {
                "requestId": payload.get("permission_id"),
                "decision": payload.get("decision"),
            },
        )
    else:
        update = {
            "sessionUpdate": "status",
            "status": {
                "eventType": event_type,
                "message": _v2_status_message(event_type, payload),
                "data": payload,
            },
        }
    return _v2_daemon_event(event, "session_update", {"update": update})


def is_v2_webshell_event(event: dict[str, Any]) -> bool:
    """Keep orchestration telemetry out of the human chat transcript."""
    return event.get("type") in {
        "task.created",
        "user.message",
        "agent.message",
        "agent.thought",
        "agent.status",
        "tool.started",
        "tool.updated",
        "tool.completed",
        "tool.failed",
        "shell.output",
        "adapter.daemon_event",
        "task.completed",
        "task.failed",
        "agent_task.failed",
        "task.cancelled",
        "permission.requested",
        "permission.resolved",
    }


def _v2_daemon_event(
    event: dict[str, Any], event_type: str, data: dict[str, Any]
) -> dict[str, Any]:
    payload = event["payload"]
    return {
        "id": event["sequence"],
        "v": 1,
        "type": event_type,
        "data": data,
        "_meta": _v2_daemon_meta(event),
    }


def _v2_daemon_meta(event: dict[str, Any]) -> dict[str, Any]:
    payload = event["payload"]
    return {
        "serverTimestamp": event["created_at"],
        "runtimeRunId": event["task_id"],
        "runtimeSequence": event["sequence"],
        "runtimeEventType": event["type"],
        "source": "agentflow-v2-webshell",
        "agentTaskId": payload.get("agent_task_id"),
        "agentRole": event.get("actor"),
        "adapter": payload.get("adapter"),
        "attempt": payload.get("attempt"),
        "executionUnitId": payload.get("execution_unit_id"),
    }


def _v2_status_message(event_type: str, payload: dict[str, Any]) -> str:
    for key in ("message", "summary", "reason", "goal"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return event_type.replace("_", " ").replace(".", " ")
