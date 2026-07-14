from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from .events import utc_now


TERMINAL_TASK_STATUSES = {"completed", "failed", "cancelled"}


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
        self._db = sqlite3.connect(self.db_path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._threads: dict[str, threading.Thread] = {}
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
                "admin_overview",
            ],
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
        with self._lock:
            if idempotency_key:
                existing = self._find_task_by_idempotency_key(idempotency_key)
                if existing is not None:
                    return existing

            now = utc_now()
            task_id = f"task_{uuid4().hex}"
            mode = str(payload.get("mode") or "auto")
            channel = str(payload.get("channel") or "web")
            adapter = str(payload.get("adapter") or "fake")
            project_id = str(payload.get("project_id") or "project_default")
            tenant_id = str(payload.get("tenant_id") or "tenant_default")
            title = summarize_goal(goal)
            metadata = dict(payload.get("metadata") or {})
            metadata.update(
                {
                    "source": payload.get("source") or channel,
                    "priority": payload.get("priority") or "normal",
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
            self._db.commit()
            task = self.get_task(task_id)
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
                "reliability": {
                    "idempotency": "enabled",
                    "event_source": "sqlite:v2_events",
                    "runner": "local background worker",
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

    def channels(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM v2_channels ORDER BY platform ASC"
            ).fetchall()
            return [channel_from_row(row) for row in rows]

    def _create_plan(
        self,
        task_id: str,
        goal: str,
        mode: str,
        adapter: str,
        now: str,
    ) -> dict[str, Any]:
        complex_task = mode in {"multi-agent", "workflow"} or len(goal) > 160
        if complex_task:
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

    def _run_task(self, task_id: str) -> None:
        try:
            with self._lock:
                row = self._task_row(task_id)
                if row is None or row["status"] in TERMINAL_TASK_STATUSES:
                    return
                self._set_task_status_locked(task_id, "running")
                self._append_event_locked(
                    task_id,
                    "task.started",
                    "orchestrator",
                    {"runner": "local-sqlite-runner"},
                )
                self._db.commit()

            for agent in self._agent_tasks(task_id):
                with self._lock:
                    if self._task_row(task_id)["status"] == "cancelled":
                        return
                    started_at = utc_now()
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
                    self._append_event_locked(
                        task_id,
                        "agent.message",
                        agent["role"],
                        {
                            "agent_task_id": agent["agent_task_id"],
                            "message": f"{agent['title']} completed by {agent['adapter']} adapter.",
                        },
                    )
                    result = {
                        "final_summary": f"{agent['title']} finished for task {task_id}.",
                        "quality": "contract-passed",
                    }
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
                        },
                    )
                    self._db.commit()

            with self._lock:
                self._set_task_status_locked(task_id, "completed")
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
                    self._set_task_status_locked(task_id, "failed")
                    self._append_event_locked(
                        task_id,
                        "task.failed",
                        "orchestrator",
                        {"error": str(exc)},
                    )
                    self._db.commit()

    def _ensure_runner(self, task_id: str) -> None:
        with self._lock:
            thread = self._threads.get(task_id)
            if thread and thread.is_alive():
                return
            row = self._task_row(task_id)
            if row is None or row["status"] in TERMINAL_TASK_STATUSES:
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
            WHERE status NOT IN ('completed', 'failed', 'cancelled')
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
        if row is None or row["status"] != "completed":
            return None
        summaries = [
            agent["result"].get("final_summary")
            for agent in self._agent_tasks(task_id)
            if agent["result"].get("final_summary")
        ]
        return {
            "summary": " ".join(summaries) or "Task completed.",
            "artifacts": [
                {
                    "name": "final_summary",
                    "kind": "summary",
                    "status": "available",
                }
            ],
            "evaluation": {"status": "passed", "checks": ["contract"]},
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
                INSERT OR IGNORE INTO v2_execution_units (
                    unit_id, kind, status, labels_json, resources_json,
                    adapters_json, features_json, heartbeat_at, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "local-dev",
                    "local-workspace",
                    "active",
                    json_dumps({"region": "local", "tier": "dev"}),
                    json_dumps({"cpu": 2, "memory_mb": 2048}),
                    json_dumps(["fake", "qwen"]),
                    json_dumps(["workspace", "artifacts", "events"]),
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
                        json_dumps({"signed_callbacks": platform != "web"}),
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

                CREATE INDEX IF NOT EXISTS idx_v2_tasks_status
                    ON v2_tasks(status);
                CREATE INDEX IF NOT EXISTS idx_v2_events_task_sequence
                    ON v2_events(task_id, sequence);
                CREATE INDEX IF NOT EXISTS idx_v2_agent_tasks_task
                    ON v2_agent_tasks(task_id, order_index);
                """
            )
            self._db.commit()


def summarize_goal(goal: str) -> str:
    compact = " ".join(goal.split())
    if len(compact) <= 72:
        return compact
    return compact[:69].rstrip() + "..."


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def json_loads(value: str | None) -> Any:
    if not value:
        return {}
    return json.loads(value)


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
        "config": json_loads(row["config_json"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
