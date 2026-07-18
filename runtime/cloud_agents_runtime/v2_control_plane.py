from __future__ import annotations

import json
import os
import signal
import shlex
import shutil
import sqlite3
import subprocess
import threading
import time
import weakref
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable
from urllib import request
from urllib.error import URLError
from uuid import uuid4

from .events import utc_now


TERMINAL_TASK_STATUSES = {"completed", "failed", "cancelled"}
SUPPORTED_MODES = {"auto", "single", "workflow", "multi-agent"}
SUPPORTED_CHANNELS = {"web", "mobile", "dingtalk", "feishu", "wecom"}
SUPPORTED_ADAPTERS = {"auto", "fake", "qwen", "codex", "claude", "opencode"}
CLI_ADAPTER_COMMAND_ENV = {
    "qwen": "V2_QWEN_CODE_COMMAND",
    "codex": "V2_CODEX_CLI_COMMAND",
    "claude": "V2_CLAUDE_CODE_COMMAND",
    "opencode": "V2_OPENCODE_COMMAND",
}
CLI_ADAPTER_DEFAULT_COMMAND = {
    "qwen": "qwen",
    "codex": "codex",
    "claude": "claude",
    "opencode": "opencode",
}
CONVERSATION_PROJECTION_VERSION = 2
MOBILE_SNAPSHOT_VERSION = 1
APPROVAL_TERMINAL_STATUSES = {
    "approved",
    "rejected",
    "expired",
    "cancelled",
    "paused",
    "revision_requested",
}


class ConversationConflictError(RuntimeError):
    """Raised when a versioned conversation update loses a compare-and-set race."""


class ApprovalConflictError(RuntimeError):
    """Raised when an approval decision is stale or already resolved."""


class ApprovalConfirmationRequiredError(RuntimeError):
    """Raised when a high-risk approval lacks explicit confirmation."""


class V2ControlPlane:
    """V2 modular-monolith control plane slice.

    This intentionally does not reuse v1 run/mission tables. It provides the
    Task-first domain model described by the V2 roadmap while staying lightweight
    enough for local product iteration.
    """

    def __init__(self, root: Path, *, auto_start: bool = True):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "control_plane.db"
        self._db = sqlite3.connect(self.db_path, check_same_thread=False)
        self._db_finalizer = weakref.finalize(self, self._db.close)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._event_condition = threading.Condition(self._lock)
        self._threads: dict[str, threading.Thread] = {}
        self._processes: dict[str, subprocess.Popen[str]] = {}
        self._remote_agent_executor: (
            Callable[[str, dict[str, Any], str, dict[str, Any]], dict[str, Any]] | None
        ) = None
        self._started = False
        self._closed = False
        self._init_db()
        self._ensure_defaults()
        self._backfill_conversations()
        if auto_start:
            self.start()

    def bind_remote_agent_executor(
        self,
        executor: Callable[[str, dict[str, Any], str, dict[str, Any]], dict[str, Any]],
    ) -> None:
        """Bind the Run Manager bridge used by remote-worker execution units."""
        with self._lock:
            if self._started:
                raise RuntimeError("remote agent executor must be bound before start")
            self._remote_agent_executor = executor

    def start(self) -> None:
        with self._lock:
            if self._started or self._closed:
                return
            self._started = True
        self._recover_open_tasks()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            processes = list(self._processes.values())
            threads = list(self._threads.values())
            for process in processes:
                terminate_process_group(process)
            self._event_condition.notify_all()
        for thread in threads:
            if thread is not threading.current_thread():
                thread.join(timeout=2)
        with self._lock:
            if self._db_finalizer.alive:
                self._db_finalizer()

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            # Interpreter shutdown may already have released locks/modules.
            pass

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
                "task_cancellation",
                "conversation_projection",
                "conversation_executions",
                "conversation_sse",
                "approval_compare_and_set",
                "mobile_triage_snapshot",
                "mobile_notification_relay",
                "admin_overview",
                "tenant_admin",
                "rbac_policy_registry",
                "bot_webhook_channels",
                "ha_profile",
                "workflow_engine_registry",
            ],
            "adapters": self.adapter_catalog(),
            "runtime": {
                "durable_engine": "local-sqlite-runner",
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
        defer_runner = bool(payload.get("_defer_runner"))
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
            project_id = str(payload.get("project_id") or "project_default")
            tenant_id = str(payload.get("tenant_id") or "tenant_default")
            title = summarize_goal(goal)
            strategy = self._strategy_for(goal, mode)
            metadata = dict(payload.get("metadata") or {})
            requested_unit_id = str(
                payload.get("execution_unit_id")
                or metadata.get("execution_unit_id")
                or ""
            ).strip() or None
            dispatch = self._dispatch_decision(
                requested_adapter=requested_adapter,
                channel=channel,
                strategy=strategy,
                requested_unit_id=requested_unit_id,
                routing_key=idempotency_key or goal,
            )
            adapter = str(dispatch["adapter"])
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
        if not defer_runner:
            self._ensure_runner(task_id)
        return task

    def list_tasks(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                """
                SELECT * FROM v2_tasks
                ORDER BY updated_at DESC, created_at DESC
                """
            ).fetchall()
            return [self._task_summary_from_row(row) for row in rows]

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

    def list_conversations(
        self,
        *,
        principal: str | None = None,
        allow_all: bool = False,
        include_archived: bool = False,
    ) -> list[dict[str, Any]]:
        with self._lock:
            clauses: list[str] = []
            values: list[Any] = []
            if not include_archived:
                clauses.append("archived_at IS NULL")
            if principal and not allow_all:
                clauses.append("created_by = ?")
                values.append(principal)
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            rows = self._db.execute(
                f"""
                SELECT * FROM v2_conversations
                {where}
                ORDER BY pinned_at IS NULL, pinned_at DESC,
                         last_meaningful_activity_at DESC, created_at DESC
                """,
                values,
            ).fetchall()
            conversations: list[dict[str, Any]] = []
            for row in rows:
                self._sync_conversation_locked(row["conversation_id"])
                current = self._conversation_row(row["conversation_id"])
                if current is not None:
                    conversations.append(self._conversation_from_row(current))
            self._db.commit()
            return conversations

    def create_conversation(
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
                existing = self._db.execute(
                    "SELECT conversation_id FROM v2_conversations WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()
                if existing is not None:
                    return self.get_conversation(
                        existing["conversation_id"],
                        principal=principal,
                    )
            now = utc_now()
            conversation_id = f"conv_{uuid4().hex}"
            self._db.execute(
                """
                INSERT INTO v2_conversations (
                    conversation_id, tenant_id, project_id, created_by, title,
                    status, unread_count, pending_approval_count, version,
                    projection_version, idempotency_key,
                    last_meaningful_activity_at, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, 0, 0, 1, ?, ?, ?, ?, ?)
                """,
                (
                    conversation_id,
                    str(payload.get("tenant_id") or "tenant_default"),
                    str(payload.get("project_id") or "project_default"),
                    principal,
                    str(payload.get("title") or summarize_goal(goal)),
                    "active",
                    CONVERSATION_PROJECTION_VERSION,
                    idempotency_key,
                    now,
                    now,
                    now,
                ),
            )
            self._db.commit()
        try:
            task_payload = dict(payload)
            task_payload["goal"] = goal
            task_payload["_defer_runner"] = True
            metadata = dict(task_payload.get("metadata") or {})
            metadata["conversation_id"] = conversation_id
            metadata["execution_sequence"] = 1
            task_payload["metadata"] = metadata
            task = self.create_task(
                task_payload,
                principal=principal,
                idempotency_key=f"conversation:{idempotency_key}"
                if idempotency_key
                else None,
            )
        except Exception:
            with self._lock:
                self._db.execute(
                    "DELETE FROM v2_conversations WHERE conversation_id = ?",
                    (conversation_id,),
                )
                self._db.commit()
            raise
        with self._lock:
            execution_id = f"exec_{uuid4().hex}"
            self._db.execute(
                """
                INSERT OR IGNORE INTO v2_executions (
                    execution_id, conversation_id, task_id, sequence, status,
                    trigger_message, idempotency_key, created_at, updated_at
                )
                VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?)
                """,
                (
                    execution_id,
                    conversation_id,
                    task["task_id"],
                    task["status"],
                    goal,
                    idempotency_key,
                    task["created_at"],
                    task["updated_at"],
                ),
            )
            execution_row = self._db.execute(
                "SELECT execution_id FROM v2_executions WHERE task_id = ?",
                (task["task_id"],),
            ).fetchone()
            if execution_row is not None:
                execution_id = execution_row["execution_id"]
            approval_spec = approval_spec_for_payload(payload, goal)
            if approval_spec is not None:
                self._create_approval_locked(
                    conversation_id=conversation_id,
                    execution_id=execution_id,
                    task_id=task["task_id"],
                    payload=approval_spec,
                    requested_by="risk-policy",
                )
            self._sync_conversation_locked(conversation_id)
            self._rebuild_conversation_projection_locked(conversation_id)
            self._db.commit()
            self._event_condition.notify_all()
            if approval_spec is None:
                self._ensure_runner(task["task_id"])
            return self.get_conversation(conversation_id, principal=principal)

    def get_conversation(
        self,
        conversation_id: str,
        *,
        principal: str | None = None,
        allow_all: bool = False,
    ) -> dict[str, Any]:
        with self._lock:
            row = self._conversation_row(conversation_id)
            if row is None:
                raise KeyError(conversation_id)
            self._assert_conversation_access(row, principal, allow_all)
            self._sync_conversation_locked(conversation_id)
            row = self._conversation_row(conversation_id)
            if row is None:
                raise KeyError(conversation_id)
            conversation = self._conversation_from_row(row)
            execution_rows = self._db.execute(
                """
                SELECT * FROM v2_executions
                WHERE conversation_id = ?
                ORDER BY sequence ASC
                """,
                (conversation_id,),
            ).fetchall()
            conversation["executions"] = [
                self._execution_from_row(execution) for execution in execution_rows
            ]
            conversation["latest_execution"] = (
                conversation["executions"][-1] if conversation["executions"] else None
            )
            self._db.commit()
            return conversation

    def conversation_for_task(
        self,
        task_id: str,
        *,
        principal: str | None = None,
        allow_all: bool = False,
    ) -> dict[str, Any]:
        with self._lock:
            row = self._db.execute(
                "SELECT conversation_id FROM v2_executions WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if row is None:
                # Legacy Task URLs are projected lazily. Conversation-native
                # reads never need to rescan the Task table.
                self._backfill_conversations_locked()
                row = self._db.execute(
                    "SELECT conversation_id FROM v2_executions WHERE task_id = ?",
                    (task_id,),
                ).fetchone()
            if row is None:
                raise KeyError(task_id)
            return self.get_conversation(
                row["conversation_id"],
                principal=principal,
                allow_all=allow_all,
            )

    def update_conversation(
        self,
        conversation_id: str,
        payload: dict[str, Any],
        *,
        principal: str,
        allow_all: bool = False,
    ) -> dict[str, Any]:
        with self._lock:
            row = self._conversation_row(conversation_id)
            if row is None:
                raise KeyError(conversation_id)
            self._assert_conversation_access(row, principal, allow_all)
            expected_version = payload.get("version")
            if expected_version is not None and int(expected_version) != int(row["version"]):
                raise ConversationConflictError("conversation version is stale")
            title = str(payload.get("title") or row["title"]).strip()
            if not title:
                raise ValueError("title is required")
            now = utc_now()
            pinned_at = row["pinned_at"]
            archived_at = row["archived_at"]
            if "pinned" in payload:
                pinned_at = now if bool(payload["pinned"]) else None
            if "archived" in payload:
                archived_at = now if bool(payload["archived"]) else None
            self._db.execute(
                """
                UPDATE v2_conversations
                SET title = ?, pinned_at = ?, archived_at = ?,
                    version = version + 1, updated_at = ?
                WHERE conversation_id = ?
                """,
                (title, pinned_at, archived_at, now, conversation_id),
            )
            self._db.commit()
            return self.get_conversation(
                conversation_id,
                principal=principal,
                allow_all=allow_all,
            )

    def conversation_messages(
        self,
        conversation_id: str,
        *,
        after: int = 0,
        before: int | None = None,
        limit: int = 200,
        principal: str | None = None,
        allow_all: bool = False,
    ) -> list[dict[str, Any]]:
        with self._lock:
            row = self._conversation_row(conversation_id)
            if row is None:
                raise KeyError(conversation_id)
            self._assert_conversation_access(row, principal, allow_all)
            self._rebuild_conversation_projection_locked(conversation_id)
            page_size = max(1, min(int(limit), 500))
            if before is not None:
                rows = self._db.execute(
                    """
                    SELECT * FROM v2_conversation_messages
                    WHERE conversation_id = ? AND cursor < ?
                    ORDER BY cursor DESC
                    LIMIT ?
                    """,
                    (conversation_id, max(0, int(before)), page_size),
                ).fetchall()
                rows = list(reversed(rows))
            elif after > 0:
                rows = self._db.execute(
                    """
                    SELECT * FROM v2_conversation_messages
                    WHERE conversation_id = ? AND cursor > ?
                    ORDER BY cursor ASC
                    LIMIT ?
                    """,
                    (conversation_id, max(0, int(after)), page_size),
                ).fetchall()
            else:
                rows = self._db.execute(
                    """
                    SELECT * FROM v2_conversation_messages
                    WHERE conversation_id = ?
                    ORDER BY cursor DESC
                    LIMIT ?
                    """,
                    (conversation_id, page_size),
                ).fetchall()
                rows = list(reversed(rows))
            self._db.commit()
            return [self._conversation_message_from_row(message) for message in rows]

    def wait_for_conversation_messages(
        self,
        conversation_id: str,
        *,
        after: int,
        timeout: float,
        principal: str | None = None,
        allow_all: bool = False,
    ) -> list[dict[str, Any]]:
        deadline = time.monotonic() + timeout
        with self._event_condition:
            while True:
                if self._closed:
                    return []
                messages = self.conversation_messages(
                    conversation_id,
                    after=after,
                    principal=principal,
                    allow_all=allow_all,
                )
                if messages:
                    return messages
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return []
                self._event_condition.wait(timeout=remaining)

    def append_conversation_message(
        self,
        conversation_id: str,
        message: str,
        *,
        principal: str,
        idempotency_key: str | None = None,
        allow_all: bool = False,
    ) -> dict[str, Any]:
        message = message.strip()
        if not message:
            raise ValueError("message is required")
        with self._lock:
            conversation = self._conversation_row(conversation_id)
            if conversation is None:
                raise KeyError(conversation_id)
            self._assert_conversation_access(conversation, principal, allow_all)
            if idempotency_key:
                existing = self._db.execute(
                    """
                    SELECT result_json FROM v2_conversation_commands
                    WHERE idempotency_key = ?
                    """,
                    (idempotency_key,),
                ).fetchone()
                if existing is not None:
                    return json_loads(existing["result_json"])
            latest = self._latest_execution_row(conversation_id)
            if latest is None:
                raise RuntimeError("conversation has no execution")
            latest_task = self._task_row(latest["task_id"])
            if latest_task is None:
                raise RuntimeError("conversation execution task is missing")
            pending_approval = self._db.execute(
                """
                SELECT 1 FROM v2_approvals
                WHERE task_id = ? AND status = 'pending'
                LIMIT 1
                """,
                (latest_task["task_id"],),
            ).fetchone()
            if latest_task["status"] in {"queued", "running"} or (
                latest_task["status"] == "waiting_user" and pending_approval is not None
            ):
                event = self.append_message(
                    latest_task["task_id"],
                    message,
                    principal=principal,
                )
                result = {
                    "conversation_id": conversation_id,
                    "execution_id": latest["execution_id"],
                    "task_id": latest["task_id"],
                    "event": event,
                    "created_execution": False,
                }
            else:
                if latest_task["status"] in {"waiting_user", "paused"}:
                    self._set_task_status_locked(latest_task["task_id"], "cancelled")
                    self._set_workflow_status_locked(latest_task["task_id"], "cancelled")
                    self._append_event_locked(
                        latest_task["task_id"],
                        "task.superseded",
                        principal,
                        {"reason": "continued after approval revision or pause"},
                    )
                sequence = int(latest["sequence"]) + 1
                previous_task = self.get_task(latest["task_id"])
                previous_dispatch = dict(
                    previous_task.get("metadata", {}).get("dispatch") or {}
                )
                task = self.create_task(
                    {
                        "goal": message,
                        "mode": previous_task["mode"],
                        "adapter": previous_task["adapter"],
                        "channel": previous_task["channel"],
                        "tenant_id": conversation["tenant_id"],
                        "project_id": conversation["project_id"],
                        "metadata": {
                            "conversation_id": conversation_id,
                            "execution_sequence": sequence,
                            "continued_from_task_id": latest["task_id"],
                            "execution_unit_id": previous_dispatch.get(
                                "execution_unit_id"
                            ),
                        },
                        "_defer_runner": True,
                    },
                    principal=principal,
                    idempotency_key=f"message:{idempotency_key}"
                    if idempotency_key
                    else None,
                )
                execution_id = f"exec_{uuid4().hex}"
                self._db.execute(
                    """
                    INSERT INTO v2_executions (
                        execution_id, conversation_id, task_id, sequence, status,
                        trigger_message, idempotency_key, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        execution_id,
                        conversation_id,
                        task["task_id"],
                        sequence,
                        task["status"],
                        message,
                        idempotency_key,
                        task["created_at"],
                        task["updated_at"],
                    ),
                )
                result = {
                    "conversation_id": conversation_id,
                    "execution_id": execution_id,
                    "task_id": task["task_id"],
                    "event": None,
                    "created_execution": True,
                }
                approval_spec = approval_spec_for_payload({}, message)
                if approval_spec is not None:
                    self._create_approval_locked(
                        conversation_id=conversation_id,
                        execution_id=execution_id,
                        task_id=task["task_id"],
                        payload=approval_spec,
                        requested_by="risk-policy",
                    )
                else:
                    self._ensure_runner(task["task_id"])
            if idempotency_key:
                self._db.execute(
                    """
                    INSERT INTO v2_conversation_commands (
                        command_id, conversation_id, idempotency_key,
                        result_json, created_at
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        f"cmd_{uuid4().hex}",
                        conversation_id,
                        idempotency_key,
                        json_dumps(result),
                        utc_now(),
                    ),
                )
            self._sync_conversation_locked(conversation_id)
            self._rebuild_conversation_projection_locked(conversation_id)
            self._db.commit()
            self._event_condition.notify_all()
            return result

    def stop_conversation(
        self,
        conversation_id: str,
        *,
        principal: str,
        reason: str | None = None,
        allow_all: bool = False,
    ) -> dict[str, Any]:
        with self._lock:
            conversation = self._conversation_row(conversation_id)
            if conversation is None:
                raise KeyError(conversation_id)
            self._assert_conversation_access(conversation, principal, allow_all)
            latest = self._latest_execution_row(conversation_id)
            if latest and latest["status"] not in TERMINAL_TASK_STATUSES:
                self.cancel_task(
                    latest["task_id"],
                    principal=principal,
                    reason=reason or "conversation stopped by user",
                )
            self._sync_conversation_locked(conversation_id)
            self._rebuild_conversation_projection_locked(conversation_id)
            self._db.commit()
            return self.get_conversation(
                conversation_id,
                principal=principal,
                allow_all=allow_all,
            )

    def conversation_activity(
        self,
        conversation_id: str,
        *,
        principal: str | None = None,
        allow_all: bool = False,
    ) -> dict[str, Any]:
        conversation = self.get_conversation(
            conversation_id,
            principal=principal,
            allow_all=allow_all,
        )
        latest = conversation.get("latest_execution")
        task = self.get_task(latest["task_id"]) if latest else None
        active_agent = None
        if task and task.get("plan"):
            active_agent = next(
                (
                    agent
                    for agent in task["plan"]["agent_tasks"]
                    if agent["status"] in {"queued", "running"}
                ),
                None,
            )
        return {
            "conversation_id": conversation_id,
            "status": conversation["status"],
            "latest_execution": latest,
            "active_agent": active_agent,
            "progress": task.get("progress") if task else None,
            "pending_approval_count": conversation["pending_approval_count"],
            "updated_at": conversation["updated_at"],
        }

    def conversation_canvas(
        self,
        conversation_id: str,
        *,
        principal: str | None = None,
        allow_all: bool = False,
    ) -> dict[str, Any]:
        conversation = self.get_conversation(
            conversation_id,
            principal=principal,
            allow_all=allow_all,
        )
        executions: list[dict[str, Any]] = []
        for execution in conversation["executions"]:
            task_id = execution["task_id"]
            task = self.get_task(task_id)
            executions.append(
                {
                    **execution,
                    "plan": task.get("plan"),
                    "workflow": self.workflow(task_id),
                    "artifacts": self.artifacts(task_id),
                    "evaluations": self.evaluations(task_id),
                    "replays": self.replays(task_id),
                    "events": task.get("events", []),
                    "progress": task.get("progress"),
                    "result": task.get("result"),
                }
            )
        return {
            "conversation_id": conversation_id,
            "projection_version": CONVERSATION_PROJECTION_VERSION,
            "executions": executions,
            "latest_execution": executions[-1] if executions else None,
        }

    def list_approvals(
        self,
        *,
        status: str | None = "pending",
        principal: str | None = None,
        allow_all: bool = False,
    ) -> list[dict[str, Any]]:
        with self._lock:
            self._expire_approvals_locked()
            clauses: list[str] = []
            values: list[Any] = []
            if status and status != "all":
                clauses.append("approval.status = ?")
                values.append(status)
            if principal and not allow_all:
                clauses.append("conversation.created_by = ?")
                values.append(principal)
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            rows = self._db.execute(
                f"""
                SELECT approval.*
                FROM v2_approvals AS approval
                JOIN v2_conversations AS conversation
                  ON conversation.conversation_id = approval.conversation_id
                {where}
                ORDER BY
                  CASE json_extract(approval.impact_json, '$.level')
                    WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2
                  END,
                  approval.created_at ASC
                """,
                values,
            ).fetchall()
            self._db.commit()
            return [self._approval_from_row(row) for row in rows]

    def get_approval(
        self,
        approval_id: str,
        *,
        principal: str | None = None,
        allow_all: bool = False,
    ) -> dict[str, Any]:
        with self._lock:
            self._expire_approvals_locked(approval_id)
            row = self._approval_row(approval_id)
            if row is None:
                raise KeyError(approval_id)
            conversation = self._conversation_row(row["conversation_id"])
            if conversation is None:
                raise KeyError(row["conversation_id"])
            self._assert_conversation_access(conversation, principal, allow_all)
            self._db.commit()
            return self._approval_from_row(row)

    def request_approval(
        self,
        conversation_id: str,
        payload: dict[str, Any],
        *,
        principal: str,
        allow_all: bool = False,
    ) -> dict[str, Any]:
        with self._lock:
            conversation = self._conversation_row(conversation_id)
            if conversation is None:
                raise KeyError(conversation_id)
            self._assert_conversation_access(conversation, principal, allow_all)
            execution = self._latest_execution_row(conversation_id)
            if execution is None:
                raise RuntimeError("conversation has no execution")
            approval = self._create_approval_locked(
                conversation_id=conversation_id,
                execution_id=execution["execution_id"],
                task_id=execution["task_id"],
                payload=payload,
                requested_by=principal,
            )
            self._sync_conversation_locked(conversation_id)
            self._rebuild_conversation_projection_locked(conversation_id)
            self._db.commit()
            self._event_condition.notify_all()
            return approval

    def decide_approval(
        self,
        approval_id: str,
        payload: dict[str, Any],
        *,
        principal: str,
        idempotency_key: str | None = None,
        allow_all: bool = False,
    ) -> dict[str, Any]:
        action = str(payload.get("action") or payload.get("decision") or "").strip()
        if action not in {"approve", "reject", "pause", "revise"}:
            raise ValueError("action must be approve, reject, pause, or revise")
        if payload.get("version") is None:
            raise ValueError("version is required")
        start_runner = False
        with self._lock:
            if idempotency_key:
                existing = self._db.execute(
                    "SELECT result_json FROM v2_approval_commands WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()
                if existing is not None:
                    return json_loads(existing["result_json"])
            self._expire_approvals_locked(approval_id)
            row = self._approval_row(approval_id)
            if row is None:
                raise KeyError(approval_id)
            conversation = self._conversation_row(row["conversation_id"])
            if conversation is None:
                raise KeyError(row["conversation_id"])
            self._assert_conversation_access(conversation, principal, allow_all)
            if row["status"] != "pending":
                raise ApprovalConflictError(
                    f"approval is already {row['status']}"
                )
            expected_version = int(payload["version"])
            if expected_version != int(row["version"]):
                raise ApprovalConflictError("approval version is stale")
            allowed_actions = json_loads(row["allowed_actions_json"])
            if action not in allowed_actions:
                raise ValueError(f"action {action} is not allowed")
            impact = json_loads(row["impact_json"])
            if (
                action == "approve"
                and impact.get("level") == "high"
                and payload.get("confirmed") is not True
            ):
                raise ApprovalConfirmationRequiredError(
                    "high-risk approval requires confirmed=true"
                )
            now = utc_now()
            next_status = {
                "approve": "approved",
                "reject": "rejected",
                "pause": "paused",
                "revise": "revision_requested",
            }[action]
            result = self._db.execute(
                """
                UPDATE v2_approvals
                SET status = ?, version = version + 1, decision = ?, reason = ?,
                    decided_by = ?, decided_at = ?, updated_at = ?
                WHERE approval_id = ? AND status = 'pending' AND version = ?
                """,
                (
                    next_status,
                    action,
                    str(payload.get("reason") or "").strip() or None,
                    principal,
                    now,
                    now,
                    approval_id,
                    expected_version,
                ),
            )
            if result.rowcount != 1:
                raise ApprovalConflictError("approval decision lost compare-and-set")
            task_id = row["task_id"]
            if action == "approve":
                self._set_task_status_locked(task_id, "queued")
                self._set_workflow_status_locked(task_id, "queued")
                start_runner = True
            elif action == "reject":
                self._set_task_status_locked(task_id, "cancelled")
                self._set_workflow_status_locked(task_id, "cancelled")
                self._append_event_locked(
                    task_id,
                    "task.cancelled",
                    principal,
                    {"reason": payload.get("reason") or "approval rejected"},
                )
            elif action == "pause":
                self._set_task_status_locked(task_id, "paused")
                self._set_workflow_status_locked(task_id, "paused")
            else:
                self._set_task_status_locked(task_id, "waiting_user")
                self._set_workflow_status_locked(task_id, "waiting_user")
            self._append_event_locked(
                task_id,
                f"approval.{next_status}",
                principal,
                {
                    "approval_id": approval_id,
                    "decision": action,
                    "reason": payload.get("reason"),
                },
            )
            self._sync_conversation_locked(row["conversation_id"])
            self._rebuild_conversation_projection_locked(row["conversation_id"])
            approval = self._approval_from_row(self._approval_row(approval_id))
            if idempotency_key:
                self._db.execute(
                    """
                    INSERT INTO v2_approval_commands (
                        command_id, approval_id, idempotency_key, result_json, created_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        f"apcmd_{uuid4().hex}",
                        approval_id,
                        idempotency_key,
                        json_dumps(approval),
                        now,
                    ),
                )
            self._db.commit()
            self._event_condition.notify_all()
            if start_runner:
                self._ensure_runner(task_id)
            return approval

    def mobile_snapshot(
        self,
        *,
        principal: str | None = None,
        allow_all: bool = False,
    ) -> dict[str, Any]:
        conversations = self.list_conversations(
            principal=principal,
            allow_all=allow_all,
            include_archived=False,
        )
        approvals = self.list_approvals(
            status="pending",
            principal=principal,
            allow_all=allow_all,
        )
        active = [
            conversation
            for conversation in conversations
            if conversation["status"] in {"active", "waiting_user"}
        ]
        recent = conversations[:20]
        return {
            "snapshot_version": MOBILE_SNAPSHOT_VERSION,
            "projection_version": CONVERSATION_PROJECTION_VERSION,
            "notification_cursor": self._latest_mobile_notification_cursor(
                principal=principal,
                allow_all=allow_all,
            ),
            "generated_at": utc_now(),
            "counts": {
                "pending_approvals": len(approvals),
                "active": sum(
                    1 for conversation in active if conversation["status"] == "active"
                ),
                "waiting_user": sum(
                    1
                    for conversation in active
                    if conversation["status"] == "waiting_user"
                ),
            },
            "approvals": approvals,
            "active_conversations": active,
            "recent_conversations": recent,
            "stateless": True,
        }

    def _latest_mobile_notification_cursor(
        self,
        *,
        principal: str | None,
        allow_all: bool,
    ) -> int:
        with self._lock:
            if principal and not allow_all:
                row = self._db.execute(
                    """
                    SELECT COALESCE(MAX(notification.cursor), 0) AS cursor
                    FROM v2_mobile_notifications AS notification
                    JOIN v2_conversations AS conversation
                      ON conversation.conversation_id = notification.conversation_id
                    WHERE conversation.created_by = ?
                    """,
                    (principal,),
                ).fetchone()
            else:
                row = self._db.execute(
                    "SELECT COALESCE(MAX(cursor), 0) AS cursor FROM v2_mobile_notifications"
                ).fetchone()
            return int(row["cursor"] if row is not None else 0)

    def mobile_notifications(
        self,
        *,
        after: int = 0,
        limit: int = 100,
        principal: str | None = None,
        allow_all: bool = False,
    ) -> list[dict[str, Any]]:
        with self._lock:
            clauses = ["notification.cursor > ?"]
            values: list[Any] = [max(0, int(after))]
            if principal and not allow_all:
                clauses.append("conversation.created_by = ?")
                values.append(principal)
            values.append(max(1, min(int(limit), 200)))
            rows = self._db.execute(
                f"""
                SELECT notification.*
                FROM v2_mobile_notifications AS notification
                JOIN v2_conversations AS conversation
                  ON conversation.conversation_id = notification.conversation_id
                WHERE {' AND '.join(clauses)}
                ORDER BY notification.cursor ASC
                LIMIT ?
                """,
                values,
            ).fetchall()
            return [self._mobile_notification_from_row(row) for row in rows]

    def wait_for_mobile_notifications(
        self,
        *,
        after: int,
        timeout: float,
        principal: str | None = None,
        allow_all: bool = False,
    ) -> list[dict[str, Any]]:
        deadline = time.monotonic() + timeout
        with self._event_condition:
            while True:
                if self._closed:
                    return []
                notifications = self.mobile_notifications(
                    after=after,
                    principal=principal,
                    allow_all=allow_all,
                )
                if notifications:
                    return notifications
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return []
                self._event_condition.wait(timeout=remaining)

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
                "driver": "postgres" if database_url else "sqlite",
                "configured": bool(database_url),
                "url_env": "V2_DATABASE_URL" if os.environ.get("V2_DATABASE_URL") else None,
            },
            "queue": {
                "driver": "redis" if queue_url else "sqlite-lease",
                "configured": bool(queue_url),
                "url_env": "V2_QUEUE_URL" if os.environ.get("V2_QUEUE_URL") else None,
            },
            "workers": {
                "horizontal_scale": bool(queue_url),
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
            if event["type"] in {"task.created", "user.message", "agent.message", "task.completed"}
        ]

    def retry_task(self, task_id: str, *, principal: str) -> dict[str, Any]:
        with self._lock:
            row = self._task_row(task_id)
            if row is None:
                raise KeyError(task_id)
            if row["status"] == "running":
                raise ValueError("task is already running")
            now = utc_now()
            self._db.execute(
                """
                UPDATE v2_agent_tasks
                SET status = ?, result_json = ?, updated_at = ?
                WHERE task_id = ?
                """,
                ("queued", json_dumps({}), now, task_id),
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
        self._ensure_runner(task_id)
        return self.get_task(task_id)

    def retry_failed_steps(self, task_id: str, *, principal: str) -> dict[str, Any]:
        with self._lock:
            row = self._task_row(task_id)
            if row is None:
                raise KeyError(task_id)
            if row["created_by"] != principal:
                raise PermissionError("task is not accessible to this principal")
            if row["status"] != "failed":
                raise ValueError("only a failed task can retry failed steps")
            now = utc_now()
            self._db.execute(
                """
                UPDATE v2_agent_tasks
                SET status = 'queued', result_json = ?, completed_at = NULL, updated_at = ?
                WHERE task_id = ? AND status != 'completed'
                """,
                (json_dumps({}), now, task_id),
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
                "task.failed_steps_retry_requested",
                principal,
                {"attempt": attempt},
            )
            self._db.commit()
        self._ensure_runner(task_id)
        return self.get_task(task_id)

    def accept_partial_result(self, task_id: str, *, principal: str) -> dict[str, Any]:
        with self._lock:
            row = self._task_row(task_id)
            if row is None:
                raise KeyError(task_id)
            if row["created_by"] != principal:
                raise PermissionError("task is not accessible to this principal")
            if row["status"] != "failed":
                raise ValueError("only a failed task can accept a partial result")
            completed = [
                agent for agent in self._agent_tasks(task_id)
                if agent["status"] == "completed"
            ]
            if not completed:
                raise ValueError("no verified partial result is available")
            self._set_task_status_locked(task_id, "completed")
            self._set_workflow_status_locked(task_id, "completed")
            self._append_event_locked(
                task_id,
                "task.partial_accepted",
                principal,
                {
                    "completed_agent_tasks": len(completed),
                    "summary": "用户接受了已经验证的部分结果。",
                },
            )
            execution = self._db.execute(
                "SELECT conversation_id FROM v2_executions WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if execution is not None:
                self._sync_conversation_locked(execution["conversation_id"])
                self._rebuild_conversation_projection_locked(
                    execution["conversation_id"]
                )
            self._db.commit()
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
            process = self._processes.get(task_id)
            if process is not None:
                terminate_process_group(process)
            self._db.execute(
                """
                UPDATE v2_agent_tasks
                SET status = ?, updated_at = ?
                WHERE task_id = ? AND status IN ('queued', 'running')
                """,
                ("cancelled", now, task_id),
            )
            self._db.execute(
                """
                UPDATE v2_workflow_steps
                SET status = ?, updated_at = ?, completed_at = ?
                WHERE task_id = ? AND status IN ('queued', 'running')
                """,
                ("cancelled", now, now, task_id),
            )
            self._append_event_locked(
                task_id,
                "task.cancelled",
                principal,
                {"reason": reason or "cancelled by user"},
            )
            approval_rows = self._db.execute(
                """
                SELECT approval_id, conversation_id FROM v2_approvals
                WHERE task_id = ? AND status = 'pending'
                """,
                (task_id,),
            ).fetchall()
            for approval_row in approval_rows:
                self._db.execute(
                    """
                    UPDATE v2_approvals
                    SET status = 'cancelled', version = version + 1,
                        decision = 'cancel', reason = ?, decided_by = ?,
                        decided_at = ?, updated_at = ?
                    WHERE approval_id = ? AND status = 'pending'
                    """,
                    (
                        reason or "conversation stopped by user",
                        principal,
                        now,
                        now,
                        approval_row["approval_id"],
                    ),
                )
                self._append_event_locked(
                    task_id,
                    "approval.cancelled",
                    principal,
                    {"approval_id": approval_row["approval_id"]},
                )
                self._sync_conversation_locked(approval_row["conversation_id"])
                self._rebuild_conversation_projection_locked(
                    approval_row["conversation_id"]
                )
            self._db.commit()
            return self.get_task(task_id)

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
                    "Clarify scope, risks, and execution order",
                    [],
                ),
                (
                    "builder",
                    "Execute the work",
                    "Produce the requested deliverable",
                    ["brain"],
                ),
                (
                    "reviewer",
                    "Review and package",
                    "Evaluate output and prepare summary",
                    ["builder"],
                ),
            ]
        else:
            strategy = "single-agent-fast-path"
            agent_specs = [
                ("agent", "Complete the task", "Finish the user goal directly", []),
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

    def _dispatch_decision(
        self,
        *,
        requested_adapter: str,
        channel: str,
        strategy: str,
        requested_unit_id: str | None = None,
        routing_key: str | None = None,
    ) -> dict[str, Any]:
        adapter = (
            self._configured_auto_adapter()
            if requested_adapter == "auto"
            else requested_adapter
        )
        unit = self._select_execution_unit(
            adapter,
            requested_unit_id=requested_unit_id,
            routing_key=routing_key,
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

    def _configured_auto_adapter(self) -> str:
        configured = normalize_choice(
            os.environ.get("V2_AUTO_ADAPTER"),
            SUPPORTED_ADAPTERS - {"auto"},
            "fake",
        )
        if configured == "fake" or self._real_cli_adapter_available(configured):
            return configured
        return "fake"

    def _real_cli_adapter_available(self, adapter: str) -> bool:
        if os.environ.get("V2_ENABLE_REAL_CLI_ADAPTERS") != "1":
            return False
        command_env = CLI_ADAPTER_COMMAND_ENV.get(adapter)
        default_command = CLI_ADAPTER_DEFAULT_COMMAND.get(adapter)
        if not command_env or not default_command:
            return False
        configured_command = os.environ.get(command_env)
        command_parts = (
            shlex.split(configured_command) if configured_command else [default_command]
        )
        return bool(command_parts and shutil.which(command_parts[0]))

    def _select_execution_unit(
        self,
        adapter: str,
        *,
        requested_unit_id: str | None = None,
        routing_key: str | None = None,
    ) -> dict[str, Any]:
        active_units = [unit for unit in self.execution_units() if unit["status"] == "active"]
        if requested_unit_id:
            requested = next(
                (unit for unit in active_units if unit["unit_id"] == requested_unit_id),
                None,
            )
            if requested is None:
                raise RuntimeError(f"execution unit {requested_unit_id} is not active")
            if adapter not in requested["adapters"]:
                raise RuntimeError(
                    f"execution unit {requested_unit_id} cannot run adapter {adapter}"
                )
            return requested

        remote_units = [
            unit
            for unit in active_units
            if adapter in unit["adapters"]
            and "remote-worker" in unit["features"]
            and self._remote_agent_executor is not None
        ]
        if remote_units:
            remote_units.sort(key=lambda unit: unit["unit_id"])
            digest = sha256((routing_key or adapter).encode("utf-8")).digest()
            return remote_units[int.from_bytes(digest[:8], "big") % len(remote_units)]
        for unit in active_units:
            if adapter in unit["adapters"]:
                return unit
        for unit in active_units:
            if "fake" in unit["adapters"]:
                return unit
        raise RuntimeError(f"no active execution unit can run adapter {adapter}")

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
                if row is None or row["status"] not in {"queued", "running"}:
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
                    self._db.execute(
                        """
                        UPDATE v2_agent_tasks
                        SET status = ?, started_at = ?, updated_at = ?
                        WHERE agent_task_id = ?
                        """,
                        ("running", started_at, started_at, agent["agent_task_id"]),
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
                with self._lock:
                    if self._task_row(task_id)["status"] == "cancelled":
                        return
                adapter_result = self._execute_agent_adapter(task_id, agent)
                if adapter_result.get("success") is False:
                    adapter_error = (
                        adapter_result.get("error")
                        or adapter_result.get("stderr")
                        or adapter_result.get("summary")
                    )
                    raise RuntimeError(
                        f"{agent['adapter']} exited with code "
                        f"{adapter_result.get('exit_code')}: "
                        f"{adapter_error}"
                    )
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
                    self._db.execute(
                        """
                        UPDATE v2_agent_tasks
                        SET status = ?, result_json = ?, completed_at = ?, updated_at = ?
                        WHERE agent_task_id = ?
                        """,
                        (
                            "completed",
                            json_dumps(result),
                            completed_at,
                            completed_at,
                            agent["agent_task_id"],
                        ),
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
                if self._task_row(task_id)["status"] == "cancelled":
                    return
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
                if self._task_row(task_id) is not None:
                    failed_at = utc_now()
                    self._set_task_status_locked(task_id, "failed")
                    self._set_workflow_status_locked(task_id, "failed")
                    self._db.execute(
                        """
                        UPDATE v2_agent_tasks
                        SET status = 'failed', completed_at = ?, updated_at = ?
                        WHERE task_id = ? AND status = 'running'
                        """,
                        (failed_at, failed_at, task_id),
                    )
                    self._db.execute(
                        """
                        UPDATE v2_workflow_steps
                        SET status = 'failed', completed_at = ?, updated_at = ?
                        WHERE task_id = ? AND status = 'running'
                        """,
                        (failed_at, failed_at, task_id),
                    )
                    self._append_event_locked(
                        task_id,
                        "task.failed",
                        "orchestrator",
                        {"error": str(exc)},
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
                "local-sqlite-dag",
                json_dumps(
                    {
                        "strategy": plan["strategy"],
                        "graph": plan["graph"],
                        "retry_policy": {
                            "max_attempts": 2,
                            "backoff_seconds": 0.1,
                        },
                        "durable_target": "temporal-compatible",
                    }
                ),
                1,
                now,
                now,
            ),
        )

    def _workflow_run(self, task_id: str) -> sqlite3.Row | None:
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
            },
        }
        if adapter == "fake":
            return simulated_adapter_result(adapter, protocol, envelope)

        task_row = self._task_row(task_id)
        if task_row is None:
            raise KeyError(task_id)
        task_goal = str(task_row["goal"])
        task_metadata = json_loads(task_row["metadata_json"])
        prompt = self._adapter_prompt(task_id, agent, task_goal)
        dispatch = dict(task_metadata.get("dispatch") or {})
        execution_unit_id = str(dispatch.get("execution_unit_id") or "")
        execution_unit = next(
            (
                unit
                for unit in self.execution_units()
                if unit["unit_id"] == execution_unit_id
            ),
            None,
        )
        if (
            execution_unit is not None
            and "remote-worker" in execution_unit["features"]
            and self._remote_agent_executor is not None
        ):
            return self._remote_agent_executor(task_id, agent, prompt, execution_unit)

        command_env = CLI_ADAPTER_COMMAND_ENV[adapter]
        default_command = CLI_ADAPTER_DEFAULT_COMMAND[adapter]
        configured_command = os.environ.get(command_env)
        command_parts = shlex.split(configured_command) if configured_command else [default_command]
        executable = shutil.which(command_parts[0])
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

        workspace = self._adapter_workspace(task_metadata)
        command = [executable, *command_parts[1:]]
        stdin_value: str | None = json_dumps(envelope)
        if adapter == "qwen":
            command.extend(["--prompt", prompt, "--output-format", "stream-json"])
            model = str(os.environ.get("V2_QWEN_MODEL") or "").strip()
            if model:
                command.extend(["--model", model])
            stdin_value = None
        timeout_seconds = max(
            20,
            min(int(os.environ.get("V2_CLI_TIMEOUT_SECONDS", "600")), 3600),
        )

        try:
            child_env = os.environ.copy()
            # A CLI agent may legitimately run this repository's tests. Do not let
            # those nested processes inherit the parent control plane's auto=qwen
            # setting and recursively launch more real agents.
            child_env["V2_ENABLE_REAL_CLI_ADAPTERS"] = "0"
            child_env["V2_AUTO_ADAPTER"] = "fake"
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=workspace,
                env=child_env,
                start_new_session=os.name == "posix",
            )
            with self._lock:
                self._processes[task_id] = process
                if self._task_row(task_id)["status"] == "cancelled":
                    terminate_process_group(process)
            try:
                stdout_value, stderr_value = process.communicate(
                    input=stdin_value,
                    timeout=timeout_seconds,
                )
            except subprocess.TimeoutExpired:
                terminate_process_group(process, force=True)
                process.communicate(timeout=5)
                raise
            finally:
                with self._lock:
                    if self._processes.get(task_id) is process:
                        self._processes.pop(task_id, None)
        except (OSError, subprocess.TimeoutExpired) as exc:
            result = simulated_adapter_result(adapter, protocol, envelope)
            result.update(
                {
                    "execution_mode": "cli-error",
                    "success": False,
                    "exit_code": None,
                    "error": str(exc),
                }
            )
            return result

        stdout = stdout_value.strip()
        stderr = stderr_value.strip()
        output = stdout or stderr or f"{adapter} completed with code {process.returncode}"
        summary = cli_result_summary(adapter, stdout) or output
        return {
            "adapter": adapter,
            "protocol": protocol,
            "execution_mode": "real-cli",
            "exit_code": process.returncode,
            "success": process.returncode == 0 and not cli_result_is_error(stdout),
            "message": summary[:4000],
            "summary": summary[:12000],
            "raw_output": stdout[:20000],
            "stderr": stderr[:4000],
            "workspace": str(workspace),
            "command": [Path(command[0]).name, *command[1:2]],
            "envelope": envelope,
        }

    def _adapter_workspace(self, metadata: dict[str, Any]) -> Path:
        configured_root = Path(
            os.environ.get("V2_WORKSPACE_ROOT") or Path.cwd()
        ).expanduser().resolve()
        requested = str(metadata.get("workspace_path") or "").strip()
        workspace = Path(requested).expanduser().resolve() if requested else configured_root
        if workspace != configured_root and configured_root not in workspace.parents:
            raise PermissionError("workspace_path must stay within V2_WORKSPACE_ROOT")
        if not workspace.is_dir():
            raise ValueError(f"workspace does not exist: {workspace}")
        return workspace

    def _adapter_prompt(
        self,
        task_id: str,
        agent: dict[str, Any],
        task_goal: str,
    ) -> str:
        role = str(agent["role"])
        role_instruction = {
            "brain": (
                "Analyze the task, inspect only what is necessary, and produce an execution "
                "plan with risks and acceptance checks. Do not modify files."
            ),
            "builder": (
                "Execute the user task in the current workspace. Use tools when needed, make "
                "requested files or changes, and verify the result."
            ),
            "reviewer": (
                "Independently review the task result and current workspace. Run relevant "
                "checks, identify residual risks, and do not modify files."
            ),
            "agent": (
                "Complete the user task directly with bounded tool calls and verify the "
                "result. Do not create subagents or nested sessions; AgentFlow owns "
                "orchestration."
            ),
        }.get(role, "Complete your assigned part and verify it.")
        prior_summaries = []
        for prior in self._agent_tasks(task_id):
            if prior["agent_task_id"] == agent["agent_task_id"]:
                break
            result = prior.get("result") or {}
            summary = str(result.get("final_summary") or "").strip()
            if summary:
                prior_summaries.append(f"- {prior['role']}: {summary[:2000]}")
        prior_context = (
            "\nPrior agent summaries:\n" + "\n".join(prior_summaries)
            if prior_summaries
            else ""
        )
        return (
            "You are one execution role in AgentFlow.\n"
            f"User task:\n{task_goal}\n\n"
            f"Your role: {role} ({agent.get('title') or role.title()})\n"
            f"Role instruction: {role_instruction}\n"
            "Coordination boundary: Do not create subagents or nested sessions; "
            "AgentFlow owns orchestration.\n"
            f"Artifact contract: {json_dumps(agent['artifact_contract'])}"
            f"{prior_context}\n\n"
            "Return a concise final report in Chinese with: outcome, evidence, checks run, "
            "and remaining risks. Never claim a command or file change that you did not verify."
        )

    def _ensure_runner(self, task_id: str) -> None:
        with self._lock:
            thread = self._threads.get(task_id)
            if thread and thread.is_alive():
                return
            row = self._task_row(task_id)
            if row is None or row["status"] not in {"queued", "running"}:
                return
            thread = threading.Thread(
                target=self._run_task,
                args=(task_id,),
                name=f"v2-task-runner-{task_id}",
                daemon=True,
            )
            self._threads[task_id] = thread
            thread.start()

    def _recover_open_tasks(self) -> None:
        rows = self._db.execute(
            """
            SELECT task_id FROM v2_tasks
            WHERE status IN ('queued', 'running')
            """
        ).fetchall()
        for row in rows:
            self._ensure_runner(row["task_id"])

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
        if row is None:
            return None
        if row["status"] == "failed":
            failure = self._db.execute(
                """
                SELECT payload_json FROM v2_events
                WHERE task_id = ? AND type = 'task.failed'
                ORDER BY sequence DESC
                LIMIT 1
                """,
                (task_id,),
            ).fetchone()
            details = json_loads(failure["payload_json"]) if failure is not None else {}
            return {
                "summary": "Task failed before its artifact contract was satisfied.",
                "error": str(details.get("error") or "unknown execution failure"),
                "artifacts": self.artifacts(task_id),
                "evaluation": {"status": "failed", "checks": [], "items": []},
            }
        if row["status"] != "completed":
            return None
        artifacts = self.artifacts(task_id)
        evaluations = self.evaluations(task_id)
        summaries = [
            agent["result"].get("final_summary")
            for agent in self._agent_tasks(task_id)
            if agent["result"].get("final_summary")
        ]
        partial = self._db.execute(
            "SELECT 1 FROM v2_events WHERE task_id = ? AND type = 'task.partial_accepted' LIMIT 1",
            (task_id,),
        ).fetchone() is not None
        return {
            "summary": " ".join(summaries) or "Task completed.",
            "artifacts": artifacts,
            "partial": partial,
            "evaluation": {
                "status": (
                    "partial"
                    if partial
                    else "passed"
                    if all(item["status"] == "passed" for item in evaluations)
                    else "failed"
                ),
                "checks": [item["kind"] for item in evaluations] or ["contract"],
                "items": evaluations,
            },
        }

    def _backfill_conversations(self) -> None:
        with self._lock:
            self._backfill_conversations_locked()
            self._db.commit()

    def _backfill_conversations_locked(self) -> None:
        rows = self._db.execute(
            """
            SELECT task.* FROM v2_tasks AS task
            LEFT JOIN v2_executions AS execution ON execution.task_id = task.task_id
            WHERE execution.task_id IS NULL
            ORDER BY task.created_at ASC
            """
        ).fetchall()
        for task in rows:
            metadata = json_loads(task["metadata_json"])
            requested_conversation_id = str(metadata.get("conversation_id") or "")
            conversation_id = requested_conversation_id or legacy_conversation_id(
                task["task_id"]
            )
            now = task["created_at"]
            self._db.execute(
                """
                INSERT OR IGNORE INTO v2_conversations (
                    conversation_id, tenant_id, project_id, created_by, title,
                    status, unread_count, pending_approval_count, version,
                    projection_version, last_meaningful_activity_at,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, 0, 0, 1, ?, ?, ?, ?)
                """,
                (
                    conversation_id,
                    task["tenant_id"],
                    task["project_id"],
                    task["created_by"],
                    task["title"],
                    conversation_status_for_task(task["status"]),
                    CONVERSATION_PROJECTION_VERSION,
                    task["updated_at"],
                    now,
                    task["updated_at"],
                ),
            )
            requested_sequence = int(metadata.get("execution_sequence") or 0)
            if requested_sequence > 0:
                sequence = requested_sequence
            else:
                sequence_row = self._db.execute(
                    """
                    SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence
                    FROM v2_executions WHERE conversation_id = ?
                    """,
                    (conversation_id,),
                ).fetchone()
                sequence = int(sequence_row["next_sequence"])
            self._db.execute(
                """
                INSERT OR IGNORE INTO v2_executions (
                    execution_id, conversation_id, task_id, sequence, status,
                    trigger_message, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    legacy_execution_id(task["task_id"]),
                    conversation_id,
                    task["task_id"],
                    sequence,
                    task["status"],
                    task["goal"],
                    task["created_at"],
                    task["updated_at"],
                ),
            )
            self._sync_conversation_locked(conversation_id)
            self._rebuild_conversation_projection_locked(conversation_id)

    def _conversation_row(self, conversation_id: str) -> sqlite3.Row | None:
        return self._db.execute(
            "SELECT * FROM v2_conversations WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()

    def _latest_execution_row(self, conversation_id: str) -> sqlite3.Row | None:
        return self._db.execute(
            """
            SELECT * FROM v2_executions
            WHERE conversation_id = ?
            ORDER BY sequence DESC
            LIMIT 1
            """,
            (conversation_id,),
        ).fetchone()

    def _assert_conversation_access(
        self,
        row: sqlite3.Row,
        principal: str | None,
        allow_all: bool,
    ) -> None:
        if principal and not allow_all and row["created_by"] != principal:
            raise PermissionError("conversation is not accessible to this principal")

    def _approval_row(self, approval_id: str) -> sqlite3.Row | None:
        return self._db.execute(
            "SELECT * FROM v2_approvals WHERE approval_id = ?",
            (approval_id,),
        ).fetchone()

    def _create_approval_locked(
        self,
        *,
        conversation_id: str,
        execution_id: str,
        task_id: str,
        payload: dict[str, Any],
        requested_by: str,
    ) -> dict[str, Any]:
        existing = self._db.execute(
            """
            SELECT * FROM v2_approvals
            WHERE task_id = ? AND status = 'pending'
            ORDER BY created_at DESC LIMIT 1
            """,
            (task_id,),
        ).fetchone()
        if existing is not None:
            return self._approval_from_row(existing)
        intent = str(payload.get("intent") or "").strip()
        if not intent:
            raise ValueError("approval intent is required")
        evidence = payload.get("evidence") or []
        if not isinstance(evidence, list) or not all(
            isinstance(item, dict) for item in evidence
        ):
            raise ValueError("approval evidence must be a list of objects")
        impact = dict(payload.get("impact") or {})
        level = str(impact.get("level") or "medium").lower()
        if level not in {"low", "medium", "high"}:
            raise ValueError("approval impact level must be low, medium, or high")
        impact = {
            "level": level,
            "summary": str(impact.get("summary") or "需要人工确认影响范围"),
            "affected_resources": [
                str(item) for item in impact.get("affected_resources") or []
            ],
            "reversible": bool(impact.get("reversible", False)),
        }
        allowed_actions = payload.get("allowed_actions") or [
            "approve",
            "reject",
            "pause",
            "revise",
        ]
        if not isinstance(allowed_actions, list) or not allowed_actions:
            raise ValueError("approval allowed_actions must be a non-empty list")
        allowed_actions = [str(action) for action in allowed_actions]
        if any(
            action not in {"approve", "reject", "pause", "revise"}
            for action in allowed_actions
        ):
            raise ValueError("approval contains an unsupported action")
        approval_id = str(payload.get("approval_id") or f"approval_{uuid4().hex}")
        now = utc_now()
        self._db.execute(
            """
            INSERT INTO v2_approvals (
                approval_id, conversation_id, execution_id, task_id,
                requested_by, intent, evidence_json, impact_json,
                allowed_actions_json, scope_json, status, version, expires_at,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', 1, ?, ?, ?)
            """,
            (
                approval_id,
                conversation_id,
                execution_id,
                task_id,
                requested_by,
                intent,
                json_dumps(evidence),
                json_dumps(impact),
                json_dumps(allowed_actions),
                json_dumps(payload.get("scope") or {}),
                payload.get("expires_at"),
                now,
                now,
            ),
        )
        self._create_mobile_notification_locked(
            conversation_id=conversation_id,
            approval_id=approval_id,
            impact_level=level,
        )
        self._set_task_status_locked(task_id, "waiting_user")
        self._set_workflow_status_locked(task_id, "waiting_user")
        self._append_event_locked(
            task_id,
            "approval.requested",
            requested_by,
            {
                "approval_id": approval_id,
                "intent": intent,
                "impact": impact,
                "evidence_count": len(evidence),
                "expires_at": payload.get("expires_at"),
            },
        )
        return self._approval_from_row(self._approval_row(approval_id))

    def _create_mobile_notification_locked(
        self,
        *,
        conversation_id: str,
        approval_id: str,
        impact_level: str,
    ) -> None:
        """Relay only a decision signal; never copy task prompts, diffs, or secrets."""
        high_risk = impact_level == "high"
        self._db.execute(
            """
            INSERT INTO v2_mobile_notifications (
                notification_id, conversation_id, approval_id, kind,
                title, body, action_path, created_at
            ) VALUES (?, ?, ?, 'approval.requested', ?, ?, ?, ?)
            """,
            (
                f"mobile_{uuid4().hex}",
                conversation_id,
                approval_id,
                "高风险操作等待确认" if high_risk else "AgentFlow 需要你的决定",
                "请打开移动决策台核对意图、证据和影响。",
                f"/approvals/{approval_id}",
                utc_now(),
            ),
        )

    def _mobile_notification_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "cursor": int(row["cursor"]),
            "notification_id": row["notification_id"],
            "kind": row["kind"],
            "title": row["title"],
            "body": row["body"],
            "action_path": row["action_path"],
            "created_at": row["created_at"],
        }

    def _expire_approvals_locked(self, approval_id: str | None = None) -> None:
        clauses = ["status = 'pending'", "expires_at IS NOT NULL"]
        values: list[Any] = []
        if approval_id:
            clauses.append("approval_id = ?")
            values.append(approval_id)
        rows = self._db.execute(
            f"SELECT * FROM v2_approvals WHERE {' AND '.join(clauses)}",
            values,
        ).fetchall()
        now = datetime.now(timezone.utc)
        for row in rows:
            if not timestamp_is_expired(row["expires_at"], now):
                continue
            updated_at = utc_now()
            self._db.execute(
                """
                UPDATE v2_approvals
                SET status = 'expired', version = version + 1,
                    updated_at = ?, decided_at = ?
                WHERE approval_id = ? AND status = 'pending'
                """,
                (updated_at, updated_at, row["approval_id"]),
            )
            self._append_event_locked(
                row["task_id"],
                "approval.expired",
                "approval-policy",
                {"approval_id": row["approval_id"]},
            )
            self._sync_conversation_locked(row["conversation_id"])
            self._rebuild_conversation_projection_locked(row["conversation_id"])

    def _approval_from_row(self, row: sqlite3.Row | None) -> dict[str, Any]:
        if row is None:
            raise KeyError("approval")
        return {
            "approval_id": row["approval_id"],
            "conversation_id": row["conversation_id"],
            "execution_id": row["execution_id"],
            "task_id": row["task_id"],
            "requested_by": row["requested_by"],
            "intent": row["intent"],
            "evidence": json_loads(row["evidence_json"]),
            "impact": json_loads(row["impact_json"]),
            "allowed_actions": json_loads(row["allowed_actions_json"]),
            "scope": json_loads(row["scope_json"]),
            "status": row["status"],
            "version": row["version"],
            "expires_at": row["expires_at"],
            "decision": row["decision"],
            "reason": row["reason"],
            "decided_by": row["decided_by"],
            "decided_at": row["decided_at"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _sync_conversation_locked(self, conversation_id: str) -> None:
        conversation = self._conversation_row(conversation_id)
        if conversation is None:
            return
        executions = self._db.execute(
            """
            SELECT execution.execution_id, execution.sequence,
                   task.status, task.updated_at
            FROM v2_executions AS execution
            JOIN v2_tasks AS task ON task.task_id = execution.task_id
            WHERE execution.conversation_id = ?
            ORDER BY execution.sequence ASC
            """,
            (conversation_id,),
        ).fetchall()
        if not executions:
            return
        for execution in executions:
            self._db.execute(
                """
                UPDATE v2_executions
                SET status = ?, updated_at = ?
                WHERE execution_id = ?
                  AND (status != ? OR updated_at != ?)
                """,
                (
                    execution["status"],
                    execution["updated_at"],
                    execution["execution_id"],
                    execution["status"],
                    execution["updated_at"],
                ),
            )
        statuses = [str(execution["status"]) for execution in executions]
        latest_status = statuses[-1]
        if any(status == "waiting_user" for status in statuses):
            status = "waiting_user"
        elif any(status in {"queued", "running"} for status in statuses):
            status = "active"
        elif latest_status == "failed":
            status = "failed"
        elif latest_status == "completed":
            status = "completed"
        else:
            status = "idle"
        pending_row = self._db.execute(
            """
            SELECT COUNT(*) AS count FROM v2_approvals
            WHERE conversation_id = ? AND status = 'pending'
            """,
            (conversation_id,),
        ).fetchone()
        pending_approval_count = int(pending_row["count"] if pending_row else 0)
        last_activity = max(str(execution["updated_at"]) for execution in executions)
        changed = (
            status != conversation["status"]
            or last_activity != conversation["last_meaningful_activity_at"]
            or pending_approval_count != int(conversation["pending_approval_count"])
        )
        if changed:
            self._db.execute(
                """
                UPDATE v2_conversations
                SET status = ?, pending_approval_count = ?,
                    last_meaningful_activity_at = ?, updated_at = ?,
                    version = version + 1
                WHERE conversation_id = ?
                """,
                (
                    status,
                    pending_approval_count,
                    last_activity,
                    last_activity,
                    conversation_id,
                ),
            )

    def _rebuild_conversation_projection_locked(
        self,
        conversation_id: str,
        *,
        force: bool = False,
    ) -> None:
        conversation = self._conversation_row(conversation_id)
        if conversation is None:
            return
        requires_full_rebuild = (
            force
            or int(conversation["projection_version"])
            != CONVERSATION_PROJECTION_VERSION
        )
        executions = self._db.execute(
            """
            SELECT * FROM v2_executions
            WHERE conversation_id = ?
            ORDER BY sequence ASC
            """,
            (conversation_id,),
        ).fetchall()
        if requires_full_rebuild:
            self._db.execute(
                "DELETE FROM v2_conversation_messages WHERE conversation_id = ?",
                (conversation_id,),
            )
        for execution in executions:
            latest_cursor = None
            if not requires_full_rebuild:
                latest_row = self._db.execute(
                    """
                    SELECT MAX(cursor) AS cursor
                    FROM v2_conversation_messages
                    WHERE conversation_id = ? AND execution_id = ?
                    """,
                    (conversation_id, execution["execution_id"]),
                ).fetchone()
                latest_cursor = latest_row["cursor"] if latest_row else None
            after_sequence = (
                max(
                    0,
                    int(latest_cursor) - int(execution["sequence"]) * 1_000_000,
                )
                if latest_cursor is not None
                else 0
            )
            events = self._db.execute(
                """
                SELECT * FROM v2_events
                WHERE task_id = ? AND sequence > ?
                ORDER BY sequence ASC
                """,
                (execution["task_id"], after_sequence),
            ).fetchall()
            for event_row in events:
                event = event_from_row(event_row)
                projection = project_conversation_event(event)
                if projection is None:
                    continue
                cursor = int(execution["sequence"]) * 1_000_000 + int(event["sequence"])
                self._db.execute(
                    """
                    INSERT OR IGNORE INTO v2_conversation_messages (
                        message_id, conversation_id, execution_id, cursor,
                        role, kind, content_json, source_event_id,
                        created_at, revision
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"msg_{event['event_id']}",
                        conversation_id,
                        execution["execution_id"],
                        cursor,
                        projection["role"],
                        projection["kind"],
                        json_dumps(projection["content"]),
                        event["event_id"],
                        event["created_at"],
                        CONVERSATION_PROJECTION_VERSION,
                    ),
                )
        if requires_full_rebuild:
            self._db.execute(
                """
                UPDATE v2_conversations
                SET projection_version = ?
                WHERE conversation_id = ?
                """,
                (CONVERSATION_PROJECTION_VERSION, conversation_id),
            )

    def _conversation_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "conversation_id": row["conversation_id"],
            "tenant_id": row["tenant_id"],
            "project_id": row["project_id"],
            "created_by": row["created_by"],
            "title": row["title"],
            "status": row["status"],
            "unread_count": row["unread_count"],
            "pending_approval_count": row["pending_approval_count"],
            "pinned_at": row["pinned_at"],
            "archived_at": row["archived_at"],
            "version": row["version"],
            "projection_version": row["projection_version"],
            "last_meaningful_activity_at": row["last_meaningful_activity_at"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _execution_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "execution_id": row["execution_id"],
            "conversation_id": row["conversation_id"],
            "task_id": row["task_id"],
            "sequence": row["sequence"],
            "status": row["status"],
            "trigger_message": row["trigger_message"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _conversation_message_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "message_id": row["message_id"],
            "conversation_id": row["conversation_id"],
            "execution_id": row["execution_id"],
            "cursor": row["cursor"],
            "role": row["role"],
            "kind": row["kind"],
            "content": json_loads(row["content_json"]),
            "created_at": row["created_at"],
            "revision": row["revision"],
        }

    def _find_task_by_idempotency_key(self, key: str) -> dict[str, Any] | None:
        row = self._db.execute(
            "SELECT task_id FROM v2_tasks WHERE idempotency_key = ?",
            (key,),
        ).fetchone()
        if row is None:
            return None
        return self.get_task(row["task_id"])

    def _task_row(self, task_id: str) -> sqlite3.Row | None:
        return self._db.execute(
            "SELECT * FROM v2_tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()

    def _task_summary_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
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
            "metadata": json_loads(row["metadata_json"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "progress": self._progress(task_id),
            "plan": self._plan_for_task(task_id),
            "result": self._result(task_id),
        }

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
        self._event_condition.notify_all()
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
        self._db.execute(
            "UPDATE v2_tasks SET status = ?, updated_at = ? WHERE task_id = ?",
            (status, utc_now(), task_id),
        )

    def _touch_task_locked(self, task_id: str, updated_at: str | None = None) -> None:
        self._db.execute(
            "UPDATE v2_tasks SET updated_at = ? WHERE task_id = ?",
            (updated_at or utc_now(), task_id),
        )

    def _ensure_defaults(self) -> None:
        now = utc_now()
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
                    os.environ.get("RUN_MANAGER_BOOTSTRAP_EMAIL", "owner@example.com"),
                    os.environ.get("RUN_MANAGER_BOOTSTRAP_EMAIL", "owner@example.com"),
                    json_dumps(["owner"]),
                    "active",
                    now,
                    now,
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
                    adapters_json = excluded.adapters_json,
                    features_json = excluded.features_json,
                    updated_at = excluded.updated_at
                """,
                (
                    "local-dev",
                    "local-workspace",
                    "active",
                    json_dumps({"region": "local", "tier": "dev"}),
                    json_dumps({"cpu": 2, "memory_mb": 2048}),
                    json_dumps(
                        ["fake"]
                        + [
                            adapter
                            for adapter in ["qwen", "codex", "claude", "opencode"]
                            if self._real_cli_adapter_available(adapter)
                        ]
                    ),
                    json_dumps(["workspace", "artifacts", "events", "cli-adapters"]),
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

                CREATE TABLE IF NOT EXISTS v2_conversations (
                    conversation_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL,
                    unread_count INTEGER NOT NULL DEFAULT 0,
                    pending_approval_count INTEGER NOT NULL DEFAULT 0,
                    pinned_at TEXT,
                    archived_at TEXT,
                    version INTEGER NOT NULL DEFAULT 1,
                    projection_version INTEGER NOT NULL,
                    idempotency_key TEXT UNIQUE,
                    last_meaningful_activity_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS v2_executions (
                    execution_id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    task_id TEXT NOT NULL UNIQUE,
                    sequence INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    trigger_message TEXT NOT NULL,
                    idempotency_key TEXT UNIQUE,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(conversation_id, sequence),
                    FOREIGN KEY(conversation_id) REFERENCES v2_conversations(conversation_id),
                    FOREIGN KEY(task_id) REFERENCES v2_tasks(task_id)
                );

                CREATE TABLE IF NOT EXISTS v2_conversation_messages (
                    message_id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    execution_id TEXT NOT NULL,
                    cursor INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    content_json TEXT NOT NULL,
                    source_event_id TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    UNIQUE(conversation_id, cursor),
                    FOREIGN KEY(conversation_id) REFERENCES v2_conversations(conversation_id),
                    FOREIGN KEY(execution_id) REFERENCES v2_executions(execution_id)
                );

                CREATE TABLE IF NOT EXISTS v2_conversation_commands (
                    command_id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(conversation_id) REFERENCES v2_conversations(conversation_id)
                );

                CREATE TABLE IF NOT EXISTS v2_approvals (
                    approval_id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    execution_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    requested_by TEXT NOT NULL,
                    intent TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    impact_json TEXT NOT NULL,
                    allowed_actions_json TEXT NOT NULL,
                    scope_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    version INTEGER NOT NULL DEFAULT 1,
                    expires_at TEXT,
                    decision TEXT,
                    reason TEXT,
                    decided_by TEXT,
                    decided_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(conversation_id) REFERENCES v2_conversations(conversation_id),
                    FOREIGN KEY(execution_id) REFERENCES v2_executions(execution_id),
                    FOREIGN KEY(task_id) REFERENCES v2_tasks(task_id)
                );

                CREATE TABLE IF NOT EXISTS v2_approval_commands (
                    command_id TEXT PRIMARY KEY,
                    approval_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(approval_id) REFERENCES v2_approvals(approval_id)
                );

                CREATE TABLE IF NOT EXISTS v2_mobile_notifications (
                    cursor INTEGER PRIMARY KEY AUTOINCREMENT,
                    notification_id TEXT NOT NULL UNIQUE,
                    conversation_id TEXT NOT NULL,
                    approval_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    action_path TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(conversation_id) REFERENCES v2_conversations(conversation_id),
                    FOREIGN KEY(approval_id) REFERENCES v2_approvals(approval_id)
                );

                CREATE INDEX IF NOT EXISTS idx_v2_tasks_status
                    ON v2_tasks(status);
                CREATE INDEX IF NOT EXISTS idx_v2_events_task_sequence
                    ON v2_events(task_id, sequence);
                CREATE INDEX IF NOT EXISTS idx_v2_agent_tasks_task
                    ON v2_agent_tasks(task_id, order_index);
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
                CREATE INDEX IF NOT EXISTS idx_v2_conversations_activity
                    ON v2_conversations(archived_at, last_meaningful_activity_at);
                CREATE INDEX IF NOT EXISTS idx_v2_executions_conversation
                    ON v2_executions(conversation_id, sequence);
                CREATE INDEX IF NOT EXISTS idx_v2_conversation_messages_cursor
                    ON v2_conversation_messages(conversation_id, cursor);
                CREATE INDEX IF NOT EXISTS idx_v2_approvals_status
                    ON v2_approvals(status, updated_at);
                CREATE INDEX IF NOT EXISTS idx_v2_approvals_conversation
                    ON v2_approvals(conversation_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_v2_mobile_notifications_conversation
                    ON v2_mobile_notifications(conversation_id, cursor);
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


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def json_loads(value: str | None) -> Any:
    if not value:
        return {}
    return json.loads(value)


def approval_spec_for_payload(
    payload: dict[str, Any], goal: str
) -> dict[str, Any] | None:
    explicit = payload.get("approval")
    if explicit is None:
        explicit = dict(payload.get("metadata") or {}).get("approval")
    if explicit is False:
        return None
    if isinstance(explicit, dict):
        return explicit
    normalized = " ".join(goal.lower().split())
    high_risk_actions = (
        "deploy to production",
        "production deploy",
        "push to production",
        "delete production",
        "drop database",
        "rotate production",
        "发布到生产",
        "生产发布",
        "部署到生产",
        "删除生产",
        "删除数据库",
        "推送到生产",
        "轮换生产",
    )
    english_risk_pair = (
        any(action in normalized for action in ("deploy", "push", "delete", "rotate"))
        and any(target in normalized for target in ("production", "prod ", " prod"))
    ) or ("drop" in normalized and "database" in normalized)
    chinese_risk_pair = any(
        action in normalized for action in ("部署", "发布", "推送", "删除", "轮换")
    ) and any(target in normalized for target in ("生产", "数据库"))
    if not (
        any(action in normalized for action in high_risk_actions)
        or english_risk_pair
        or chinese_risk_pair
    ):
        return None
    return {
        "intent": summarize_goal(goal),
        "evidence": [
            {
                "type": "user_request",
                "label": "触发审批的用户指令",
                "summary": goal[:500],
            }
        ],
        "impact": {
            "level": "high",
            "summary": "该操作可能改变生产环境，执行前需要你明确确认。",
            "affected_resources": ["production"],
            "reversible": False,
        },
        "allowed_actions": ["approve", "reject", "pause", "revise"],
        "scope": {"environment": "production", "source": "risk-policy"},
    }


def timestamp_is_expired(value: str, now: datetime | None = None) -> bool:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed <= (now or datetime.now(timezone.utc))


def terminate_process_group(
    process: subprocess.Popen[str],
    *,
    force: bool = False,
) -> None:
    """Terminate a CLI and descendants that inherited its stdio pipes."""

    try:
        if os.name == "posix":
            os.killpg(
                os.getpgid(process.pid),
                signal.SIGKILL if force else signal.SIGTERM,
            )
        elif process.poll() is None:
            process.kill() if force else process.terminate()
    except (OSError, ProcessLookupError):
        if process.poll() is None:
            try:
                process.kill() if force else process.terminate()
            except OSError:
                pass


def cli_result_summary(adapter: str, stdout: str) -> str | None:
    if not stdout:
        return None
    events = cli_result_events(stdout)
    if not events:
        return stdout
    for event in reversed(events):
        if not isinstance(event, dict):
            continue
        if event.get("type") == "result" and isinstance(event.get("result"), str):
            return str(event["result"])
        if adapter == "qwen":
            message = event.get("message")
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, list):
                    texts = [
                        str(item.get("text"))
                        for item in content
                        if isinstance(item, dict)
                        and item.get("type") == "text"
                        and item.get("text")
                    ]
                    if texts:
                        return "\n".join(texts)
    return stdout


def cli_result_is_error(stdout: str) -> bool:
    if not stdout:
        return False
    events = cli_result_events(stdout)
    return any(
        isinstance(event, dict)
        and event.get("type") == "result"
        and event.get("is_error") is True
        for event in events
    )


def cli_result_events(stdout: str) -> list[dict[str, Any]]:
    """Decode supported headless CLI formats without leaking startup noise.

    Qwen normally returns one JSON array, but optional MCP startup warnings can
    precede it and stream-json returns one object per line. Keep the raw output
    for audit evidence while extracting only structured event objects for the
    user-facing summary and success decision.
    """

    if not stdout:
        return []

    def normalize(value: Any) -> list[dict[str, Any]]:
        values = value if isinstance(value, list) else [value]
        return [item for item in values if isinstance(item, dict)]

    decoders = (json.JSONDecoder(), json.JSONDecoder(strict=False))
    for decoder in decoders:
        try:
            events = normalize(decoder.decode(stdout))
        except (json.JSONDecodeError, TypeError):
            continue
        if events:
            return events

    line_events: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        candidate = line.strip()
        if not candidate or candidate[0] not in "[{":
            continue
        for decoder in decoders:
            try:
                decoded = decoder.decode(candidate)
            except (json.JSONDecodeError, TypeError):
                continue
            line_events.extend(normalize(decoded))
            break
    if any(event.get("type") == "result" for event in line_events):
        return line_events

    scanned_events = list(line_events)
    position = 0
    while position < len(stdout):
        candidates = [
            index
            for token in ("[", "{")
            for index in [stdout.find(token, position)]
            if index >= 0
        ]
        if not candidates:
            break
        start = min(candidates)
        decoded_value: Any | None = None
        consumed = 0
        for decoder in decoders:
            try:
                decoded_value, consumed = decoder.raw_decode(stdout[start:])
            except (json.JSONDecodeError, TypeError):
                continue
            break
        if consumed:
            scanned_events.extend(normalize(decoded_value))
            position = start + consumed
        else:
            position = start + 1
    return scanned_events


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


def legacy_conversation_id(task_id: str) -> str:
    return f"conv_{task_id.removeprefix('task_')}"


def legacy_execution_id(task_id: str) -> str:
    return f"exec_{task_id.removeprefix('task_')}"


def conversation_status_for_task(status: str) -> str:
    if status in {"queued", "running"}:
        return "active"
    if status == "waiting_user":
        return "waiting_user"
    if status == "failed":
        return "failed"
    if status == "completed":
        return "completed"
    return "idle"


def project_conversation_event(event: dict[str, Any]) -> dict[str, Any] | None:
    event_type = str(event.get("type") or "")
    payload = dict(event.get("payload") or {})

    def text_block(text: Any) -> dict[str, str]:
        return {"type": "text", "text": str(text or "")}

    if event_type == "task.created":
        return {
            "role": "user",
            "kind": "text",
            "content": [text_block(payload.get("goal") or payload.get("title"))],
        }
    if event_type == "user.message":
        return {
            "role": "user",
            "kind": "text",
            "content": [text_block(payload.get("message"))],
        }
    if event_type == "plan.created":
        return {
            "role": "agent",
            "kind": "plan",
            "content": [
                text_block(
                    f"已生成执行计划，将由 {int(payload.get('agent_task_count') or 0)} 个 Agent 协作完成。"
                ),
                {
                    "type": "entity_ref",
                    "entity_type": "plan",
                    "entity_id": str(payload.get("plan_id") or ""),
                    "label": "查看计划与 Agent",
                },
            ],
        }
    if event_type == "task.started":
        return {
            "role": "system",
            "kind": "brief",
            "content": [text_block("执行已经开始，任务会在后台持续推进。")],
        }
    if event_type == "agent.message":
        agent_task_id = str(payload.get("agent_task_id") or "")
        return {
            "role": "agent",
            "kind": "brief",
            "content": [
                text_block(payload.get("message")),
                {
                    "type": "entity_ref",
                    "entity_type": "agents",
                    "entity_id": agent_task_id,
                    "label": "在 Canvas 查看此 Agent",
                },
            ]
            if agent_task_id
            else [text_block(payload.get("message"))],
        }
    if event_type == "task.completed":
        return {
            "role": "agent",
            "kind": "result",
            "content": [
                text_block(payload.get("summary") or "工作已完成。"),
                {
                    "type": "entity_ref",
                    "entity_type": "artifacts",
                    "entity_id": str(event.get("task_id") or ""),
                    "label": "查看产物与验收结果",
                },
            ],
        }
    if event_type == "task.partial_accepted":
        return {
            "role": "agent",
            "kind": "result",
            "content": [
                text_block(payload.get("summary") or "已保留并接受通过验证的部分结果。"),
                {
                    "type": "entity_ref",
                    "entity_type": "artifacts",
                    "entity_id": str(event.get("task_id") or ""),
                    "label": "查看已生成的产物",
                },
            ],
        }
    if event_type == "task.failed":
        return {
            "role": "system",
            "kind": "error",
            "content": [
                text_block(
                    f"执行未能完成：{payload.get('error') or '未知错误'}。你可以调整要求后继续。"
                )
            ],
        }
    if event_type == "task.cancelled":
        return {
            "role": "system",
            "kind": "brief",
            "content": [text_block("任务已停止。你可以补充要求后发起新的执行。")],
        }
    if event_type == "approval.requested":
        return {
            "role": "system",
            "kind": "approval",
            "content": [
                text_block(payload.get("intent") or "需要你的批准后才能继续。"),
                {
                    "type": "entity_ref",
                    "entity_type": "approval",
                    "entity_id": str(payload.get("approval_id") or ""),
                    "label": "查看审批",
                },
            ],
        }
    if event_type.startswith("approval.") and event_type != "approval.requested":
        action = event_type.split(".", 1)[1]
        return {
            "role": "system",
            "kind": "brief",
            "content": [text_block(f"审批状态已更新：{action}。")],
        }
    return None


def event_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "event_id": row["event_id"],
        "task_id": row["task_id"],
        "sequence": row["sequence"],
        "type": row["type"],
        "actor": row["actor"],
        "payload": json_loads(row["payload_json"]),
        "created_at": row["created_at"],
    }


def agent_task_from_row(row: sqlite3.Row) -> dict[str, Any]:
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


def unit_from_row(row: sqlite3.Row) -> dict[str, Any]:
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


def channel_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "channel_id": row["channel_id"],
        "platform": row["platform"],
        "status": row["status"],
        "config": redact_secret_config(json_loads(row["config_json"])),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def channel_message_from_row(row: sqlite3.Row) -> dict[str, Any]:
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


def tenant_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "tenant_id": row["tenant_id"],
        "name": row["name"],
        "status": row["status"],
        "settings": json_loads(row["settings_json"]),
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def tenant_user_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "tenant_id": row["tenant_id"],
        "user_id": row["user_id"],
        "email": row["email"],
        "roles": json_loads(row["roles_json"]),
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def rbac_policy_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "tenant_id": row["tenant_id"],
        "role": row["role"],
        "permissions": json_loads(row["permissions_json"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def workflow_run_from_row(row: sqlite3.Row) -> dict[str, Any]:
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


def workflow_step_from_row(row: sqlite3.Row) -> dict[str, Any]:
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


def artifact_from_row(row: sqlite3.Row) -> dict[str, Any]:
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


def evaluation_from_row(row: sqlite3.Row) -> dict[str, Any]:
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


def replay_from_row(row: sqlite3.Row) -> dict[str, Any]:
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
        "secret",
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
    if event_type == "user.message":
        update = {
            "sessionUpdate": "user_message_chunk",
            "content": {"type": "text", "text": str(payload.get("message") or "")},
        }
    elif event_type == "agent.message":
        update = {
            "sessionUpdate": "agent_message_chunk",
            "content": {"type": "text", "text": str(payload.get("message") or "")},
        }
    elif event_type == "task.completed":
        update = {
            "sessionUpdate": "agent_message_chunk",
            "content": {"type": "text", "text": str(payload.get("summary") or "Done")},
        }
    else:
        update = {
            "sessionUpdate": "system_message_chunk",
            "content": {"type": "text", "text": str(payload.get("goal") or "")},
        }
    return {
        "id": event["sequence"],
        "v": 1,
        "type": "session_update",
        "data": {"update": update},
        "_meta": {
            "serverTimestamp": event["created_at"],
            "runtimeRunId": event["task_id"],
            "runtimeSequence": event["sequence"],
            "runtimeEventType": event_type,
            "source": "agentflow-v2-webshell",
        },
    }
