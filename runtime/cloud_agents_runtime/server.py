from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from . import __version__
from .access import roles_allow, scopes_allow
from .auth import AuthConfig, hash_password, is_authorized, verify_password
from .executors import ExecutorConfig
from .interop import (
    a2a_agent_card,
    a2a_task_from_mission,
    create_a2a_task,
    handle_acp_jsonrpc,
)
from .manager import RunManager
from .models import RunSpec
from .supervisor import qwen_supervisor_from_env
from .temporal_poc import agent_run_workflow_plan, mission_workflow_plan
from .ui_projection import project_event, project_events
from .v2_control_plane import v2_event_to_daemon_event


def make_handler(
    manager: RunManager,
    auth_config: AuthConfig | None = None,
) -> type[BaseHTTPRequestHandler]:
    auth_config = auth_config or AuthConfig()
    if auth_config.login_enabled:
        manager.store.ensure_auth_user(
            email=auth_config.bootstrap_email_value or "",
            display_name=auth_config.bootstrap_display_name
            or auth_config.bootstrap_email_value
            or "Cloud Agents Owner",
            password_hash=hash_password(auth_config.bootstrap_password_value or ""),
            roles=["owner"],
            email_verified=True,
            rotate_password=True,
        )
    login_failures: dict[str, list[float]] = {}

    class RuntimeHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = f"agentflow-runtime/{__version__}"
        current_identity: dict[str, Any] | None = None

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path == "/auth/session":
                self.write_json(auth_config.session_status(self.session_identity()))
                return
            spa_target = spa_redirect_target(path, self.headers)
            if spa_target:
                self.write_redirect(spa_target)
                return
            if not self.require_auth(path):
                return
            parts = split_path(path)
            if path in {"/", "/ui"}:
                self.write_html(load_index_html())
                return
            static_path = resolve_static_path(path)
            if static_path is not None:
                self.write_static_file(static_path)
                return
            if path == "/health":
                self.write_json({"ok": True, "version": __version__})
                return
            if path == "/v2/capabilities":
                self.write_json(manager.v2.capabilities())
                return
            if path == "/v2/tasks":
                self.write_json(
                    {
                        "tasks": manager.v2.list_tasks(
                            principal=self.principal_id(), roles=self.current_roles()
                        )
                    }
                )
                return
            if len(parts) == 3 and parts[0] == "v2" and parts[1] == "tasks":
                if not self.authorize_v2_task(unquote(parts[2])):
                    return
                try:
                    self.write_json(manager.v2.get_task(unquote(parts[2])))
                except KeyError:
                    self.write_error(HTTPStatus.NOT_FOUND, "task not found")
                return
            if (
                len(parts) == 4
                and parts[0] == "v2"
                and parts[1] == "tasks"
                and parts[3] == "events.json"
            ):
                if not self.authorize_v2_task(unquote(parts[2])):
                    return
                try:
                    self.write_json({"events": manager.v2.events(unquote(parts[2]))})
                except KeyError:
                    self.write_error(HTTPStatus.NOT_FOUND, "task not found")
                return
            if (
                len(parts) == 5
                and parts[0] == "v2"
                and parts[1] == "tasks"
                and parts[3] == "webshell"
                and parts[4] == "events"
            ):
                self.stream_v2_webshell_events(unquote(parts[2]))
                return
            if (
                len(parts) == 5
                and parts[0] == "v2"
                and parts[1] == "tasks"
                and parts[3] == "webshell"
                and parts[4] == "events.json"
            ):
                if not self.authorize_v2_task(unquote(parts[2])):
                    return
                try:
                    self.write_json({"events": manager.v2.webshell_events(unquote(parts[2]))})
                except KeyError:
                    self.write_error(HTTPStatus.NOT_FOUND, "task not found")
                return
            if (
                len(parts) == 4
                and parts[0] == "v2"
                and parts[1] == "tasks"
                and parts[3] == "workflow"
            ):
                if not self.authorize_v2_task(unquote(parts[2])):
                    return
                try:
                    self.write_json(manager.v2.workflow(unquote(parts[2])))
                except KeyError:
                    self.write_error(HTTPStatus.NOT_FOUND, "task not found")
                return
            if (
                len(parts) == 4
                and parts[0] == "v2"
                and parts[1] == "tasks"
                and parts[3] == "artifacts"
            ):
                if not self.authorize_v2_task(unquote(parts[2])):
                    return
                try:
                    self.write_json({"artifacts": manager.v2.artifacts(unquote(parts[2]))})
                except KeyError:
                    self.write_error(HTTPStatus.NOT_FOUND, "task not found")
                return
            if (
                len(parts) == 5
                and parts[0] == "v2"
                and parts[1] == "tasks"
                and parts[3] == "artifacts"
            ):
                if not self.authorize_v2_task(unquote(parts[2])):
                    return
                try:
                    self.write_json(
                        manager.v2.artifact(unquote(parts[2]), unquote(parts[4]))
                    )
                except KeyError:
                    self.write_error(HTTPStatus.NOT_FOUND, "artifact not found")
                return
            if (
                len(parts) == 4
                and parts[0] == "v2"
                and parts[1] == "tasks"
                and parts[3] == "audit.json"
            ):
                if not self.authorize_v2_task(unquote(parts[2])):
                    return
                try:
                    self.write_json(manager.v2.audit_bundle(unquote(parts[2])))
                except KeyError:
                    self.write_error(HTTPStatus.NOT_FOUND, "task not found")
                return
            if (
                len(parts) == 4
                and parts[0] == "v2"
                and parts[1] == "tasks"
                and parts[3] == "evaluations"
            ):
                if not self.authorize_v2_task(unquote(parts[2])):
                    return
                try:
                    self.write_json(
                        {"evaluations": manager.v2.evaluations(unquote(parts[2]))}
                    )
                except KeyError:
                    self.write_error(HTTPStatus.NOT_FOUND, "task not found")
                return
            if (
                len(parts) == 4
                and parts[0] == "v2"
                and parts[1] == "tasks"
                and parts[3] == "replays"
            ):
                if not self.authorize_v2_task(unquote(parts[2])):
                    return
                try:
                    self.write_json({"replays": manager.v2.replays(unquote(parts[2]))})
                except KeyError:
                    self.write_error(HTTPStatus.NOT_FOUND, "task not found")
                return
            if path == "/v2/admin/overview":
                self.write_json(manager.v2.admin_overview())
                return
            if path == "/v2/admin/execution-units":
                self.write_json({"units": manager.v2.execution_units()})
                return
            if path == "/v2/admin/channels":
                self.write_json({"channels": manager.v2.channels()})
                return
            if path == "/v2/admin/channel-messages":
                self.write_json({"messages": manager.v2.channel_messages()})
                return
            if path == "/v2/admin/tenants":
                self.write_json({"tenants": manager.v2.tenants()})
                return
            if path == "/v2/admin/projects":
                self.write_json({"projects": manager.v2.projects()})
                return
            if (
                len(parts) == 5
                and parts[:3] == ["v2", "admin", "projects"]
                and parts[4] == "members"
            ):
                self.write_json(
                    {"members": manager.v2.project_members(unquote(parts[3]))}
                )
                return
            if (
                len(parts) == 5
                and parts[0] == "v2"
                and parts[1] == "admin"
                and parts[2] == "tenants"
                and parts[4] == "users"
            ):
                self.write_json({"users": manager.v2.tenant_users(unquote(parts[3]))})
                return
            if (
                len(parts) == 5
                and parts[0] == "v2"
                and parts[1] == "admin"
                and parts[2] == "tenants"
                and parts[4] == "rbac"
            ):
                self.write_json({"policies": manager.v2.rbac_policies(unquote(parts[3]))})
                return
            if path == "/v2/admin/ha":
                self.write_json(manager.v2.ha_config())
                return
            if path == "/v2/admin/workflow-engines":
                self.write_json(manager.v2.workflow_engine_status())
                return
            if path == "/capabilities":
                self.write_json(manager.capabilities())
                return
            if path == "/acp":
                self.write_json(
                    {
                        "protocol": "acp-poc",
                        "protocol_version": "cloud-agents-acp-compat-2026-07",
                        "transport": "json-rpc-over-http",
                        "endpoint": "/acp",
                        "event_stream": "/runs/{run_id}/events",
                    }
                )
                return
            if path == "/.well-known/agent-card.json":
                self.write_json(a2a_agent_card(manager, self.base_url()))
                return
            if path == "/queue":
                self.write_json(manager.queue_status())
                return
            if path == "/workers":
                self.write_json({"workers": manager.queue_status()["workers"]})
                return
            if len(parts) == 2 and parts[0] == "permissions" and parts[1] == "notifications":
                self.write_json({"notifications": manager.list_permission_notifications()})
                return
            if len(parts) == 2 and parts[0] == "workers":
                worker_id = unquote(parts[1])
                for worker in manager.queue_status()["workers"]:
                    if worker["worker_id"] == worker_id:
                        self.write_json({"worker": worker})
                        return
                self.write_error(HTTPStatus.NOT_FOUND, "worker not found")
                return
            if len(parts) == 3 and parts[0] == "workers" and parts[2] == "control":
                self.write_json(manager.remote_worker_control(unquote(parts[1])))
                return
            if path == "/executors":
                self.write_json(manager.executors())
                return
            if path == "/metrics.json":
                self.write_json(manager.metrics())
                return
            if path == "/ops/status":
                self.write_json(manager.operations_status())
                return
            if path == "/cost/status":
                self.write_json(manager.cost_status())
                return
            if path == "/ops/drills":
                self.write_json(manager.run_drills())
                return
            if path == "/ops/backups":
                self.write_json({"backups": manager.list_backups()})
                return
            if path == "/access/policy":
                self.write_json(
                    manager.access_policy(
                        self.headers,
                        principal=self.principal_id(),
                        roles=self.current_roles(),
                    )
                )
                return
            if path == "/access/projects":
                self.write_json(manager.list_access_projects())
                return
            if path == "/access/tokens":
                self.write_json(manager.list_api_tokens())
                return
            if path == "/auth/users":
                self.write_json(
                    {"users": [user.to_dict() for user in manager.store.list_auth_users()]}
                )
                return
            if len(parts) == 3 and parts[0] == "ops" and parts[1] == "backups":
                try:
                    self.write_file(manager.backup_path(unquote(parts[2])))
                except ValueError as exc:
                    self.write_error(HTTPStatus.BAD_REQUEST, str(exc))
                except FileNotFoundError:
                    self.write_error(HTTPStatus.NOT_FOUND, "backup not found")
                return
            if path == "/p5/evaluations":
                self.write_json(manager.p5_evaluations())
                return
            if len(parts) == 1 and parts[0] == "profiles":
                self.write_json({"profiles": manager.list_profiles()})
                return
            if len(parts) == 2 and parts[0] == "profiles":
                profile = manager.get_profile(parts[1])
                if profile is None:
                    self.write_error(HTTPStatus.NOT_FOUND, "profile not found")
                    return
                self.write_json(profile)
                return
            if len(parts) == 1 and parts[0] == "missions":
                self.write_json({"missions": manager.list_missions()})
                return
            if len(parts) == 1 and parts[0] == "tasks":
                self.write_json({"tasks": manager.list_tasks(self.access_context())})
                return
            if len(parts) == 2 and parts[0] == "tasks":
                task = manager.get_task(
                    unquote(parts[1]),
                    access_context=self.access_context(),
                )
                if task is None:
                    self.write_error(HTTPStatus.NOT_FOUND, "task not found")
                    return
                self.write_json(task)
                return
            if len(parts) == 3 and parts[0] == "tasks" and parts[2] == "events.json":
                try:
                    self.write_json(
                        {
                            "events": manager.task_events(
                                unquote(parts[1]),
                                access_context=self.access_context(),
                            )
                        }
                    )
                except KeyError:
                    self.write_error(HTTPStatus.NOT_FOUND, "task not found")
                return
            if len(parts) == 3 and parts[0] == "tasks" and parts[2] == "artifacts":
                try:
                    self.write_json(
                        {
                            "artifacts": manager.task_artifacts(
                                unquote(parts[1]),
                                access_context=self.access_context(),
                            )
                        }
                    )
                except KeyError:
                    self.write_error(HTTPStatus.NOT_FOUND, "task not found")
                return
            if len(parts) == 3 and parts[0] == "tasks" and parts[2] == "result":
                try:
                    self.write_json(
                        manager.task_result(
                            unquote(parts[1]),
                            access_context=self.access_context(),
                        )
                    )
                except KeyError:
                    self.write_error(HTTPStatus.NOT_FOUND, "task not found")
                return
            if len(parts) == 2 and parts[0] == "a2a" and parts[1] == "tasks":
                self.write_json({"tasks": manager.list_missions()})
                return
            if len(parts) == 3 and parts[0] == "a2a" and parts[1] == "tasks":
                try:
                    self.write_json(a2a_task_from_mission(manager, parts[2]))
                except KeyError:
                    self.write_error(HTTPStatus.NOT_FOUND, "task not found")
                return
            if (
                len(parts) == 4
                and parts[0] == "a2a"
                and parts[1] == "tasks"
                and parts[3] == "events.json"
            ):
                try:
                    events = manager.store.mission_events_since(parts[2])
                except KeyError:
                    self.write_error(HTTPStatus.NOT_FOUND, "task not found")
                    return
                self.write_json({"events": [event.to_dict() for event in events]})
                return
            if (
                len(parts) == 4
                and parts[0] == "a2a"
                and parts[1] == "tasks"
                and parts[3] == "artifacts"
            ):
                try:
                    artifacts = manager.store.list_mission_artifacts(parts[2])
                except KeyError:
                    self.write_error(HTTPStatus.NOT_FOUND, "task not found")
                    return
                self.write_json({"artifacts": artifacts})
                return
            if len(parts) == 2 and parts[0] == "missions":
                mission = manager.get_mission(parts[1])
                if mission is None:
                    self.write_error(HTTPStatus.NOT_FOUND, "mission not found")
                    return
                self.write_json(mission)
                return
            if len(parts) == 3 and parts[0] == "missions" and parts[2] == "events.json":
                try:
                    events = manager.store.mission_events_since(parts[1])
                except KeyError:
                    self.write_error(HTTPStatus.NOT_FOUND, "mission not found")
                    return
                self.write_json({"events": [event.to_dict() for event in events]})
                return
            if len(parts) == 3 and parts[0] == "missions" and parts[2] == "artifacts":
                try:
                    artifacts = manager.store.list_mission_artifacts(parts[1])
                except KeyError:
                    self.write_error(HTTPStatus.NOT_FOUND, "mission not found")
                    return
                self.write_json({"artifacts": artifacts})
                return
            if len(parts) == 4 and parts[0] == "missions" and parts[2] == "artifacts":
                try:
                    self.write_file(
                        manager.store.mission_artifact_path(parts[1], unquote(parts[3]))
                    )
                except KeyError:
                    self.write_error(HTTPStatus.NOT_FOUND, "mission not found")
                except ValueError as exc:
                    self.write_error(HTTPStatus.BAD_REQUEST, str(exc))
                except FileNotFoundError:
                    self.write_error(HTTPStatus.NOT_FOUND, "artifact not found")
                return
            if (
                len(parts) == 5
                and parts[0] == "temporal"
                and parts[1] == "workflows"
                and parts[2] == "missions"
                and parts[4] == "plan"
            ):
                mission = manager.get_mission(parts[3])
                if mission is None:
                    self.write_error(HTTPStatus.NOT_FOUND, "mission not found")
                    return
                self.write_json(mission_workflow_plan(mission))
                return
            if len(parts) == 1 and parts[0] == "runs":
                self.write_json({"runs": [run.to_dict() for run in manager.store.list_runs()]})
                return
            if len(parts) == 2 and parts[0] == "runs":
                run = manager.get_run(parts[1])
                if run is None:
                    self.write_error(HTTPStatus.NOT_FOUND, "run not found")
                    return
                self.write_json(run.to_dict())
                return
            if len(parts) == 3 and parts[0] == "runs" and parts[2] == "executor":
                if manager.get_run(parts[1]) is None:
                    self.write_error(HTTPStatus.NOT_FOUND, "run not found")
                    return
                lease = manager.store.get_executor_lease_for_run(parts[1])
                self.write_json({"executor": lease.to_dict() if lease else None})
                return
            if (
                len(parts) == 5
                and parts[0] == "temporal"
                and parts[1] == "workflows"
                and parts[2] == "runs"
                and parts[4] == "plan"
            ):
                run = manager.get_run(parts[3])
                if run is None:
                    self.write_error(HTTPStatus.NOT_FOUND, "run not found")
                    return
                self.write_json(agent_run_workflow_plan(run))
                return
            if len(parts) == 3 and parts[0] == "runs" and parts[2] == "events":
                self.stream_events(parts[1])
                return
            if len(parts) == 3 and parts[0] == "session" and parts[2] == "events":
                self.stream_session_events(parts[1])
                return
            if len(parts) == 3 and parts[0] == "session" and parts[2] == "events.json":
                try:
                    projected = self.projected_session_events(parts[1])
                except KeyError:
                    self.write_error(HTTPStatus.NOT_FOUND, "session not found")
                    return
                self.write_json({"events": projected})
                return
            if (
                len(parts) == 3
                and parts[0] == "runs"
                and parts[2] == "permission-notifications"
            ):
                self.write_json(
                    {
                        "notifications": manager.list_permission_notifications(
                            run_id=parts[1],
                        )
                    }
                )
                return
            if len(parts) == 3 and parts[0] == "runs" and parts[2] == "events.json":
                try:
                    events = manager.store.events_since(parts[1])
                except KeyError:
                    self.write_error(HTTPStatus.NOT_FOUND, "run not found")
                    return
                self.write_json({"events": [event.to_dict() for event in events]})
                return
            if len(parts) == 3 and parts[0] == "runs" and parts[2] == "audit.json":
                try:
                    self.write_json(manager.run_audit_bundle(parts[1]))
                except KeyError:
                    self.write_error(HTTPStatus.NOT_FOUND, "run not found")
                return
            if len(parts) == 3 and parts[0] == "runs" and parts[2] == "artifacts":
                try:
                    artifacts = manager.store.list_artifacts(parts[1])
                except KeyError:
                    self.write_error(HTTPStatus.NOT_FOUND, "run not found")
                    return
                self.write_json({"artifacts": artifacts})
                return
            if len(parts) == 4 and parts[0] == "runs" and parts[2] == "artifacts":
                try:
                    self.write_file(manager.store.artifact_path(parts[1], unquote(parts[3])))
                except KeyError:
                    self.write_error(HTTPStatus.NOT_FOUND, "run not found")
                except ValueError as exc:
                    self.write_error(HTTPStatus.BAD_REQUEST, str(exc))
                except FileNotFoundError:
                    self.write_error(HTTPStatus.NOT_FOUND, "artifact not found")
                return
            self.write_error(HTTPStatus.NOT_FOUND, "not found")

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            if path == "/auth/login":
                self.handle_login()
                return
            if path == "/auth/logout":
                manager.store.revoke_auth_session(
                    auth_config.session_token(self.headers.get("cookie"))
                )
                self.write_json(
                    {"authenticated": False},
                    headers={
                        "set-cookie": auth_config.clear_session_cookie(
                            cookie_path=self.cookie_path(),
                            secure=self.is_secure_request(),
                        )
                    },
                )
                return
            parts = split_path(path)
            if (
                len(parts) == 4
                and parts[0] == "v2"
                and parts[1] == "channels"
                and parts[3] == "webhook"
            ):
                try:
                    payload = self.read_json()
                    received = manager.v2.receive_channel_message(
                        unquote(parts[2]),
                        payload,
                        headers=dict(self.headers.items()),
                    )
                except PermissionError as exc:
                    self.write_error(HTTPStatus.FORBIDDEN, str(exc))
                    return
                except ValueError as exc:
                    self.write_error(HTTPStatus.BAD_REQUEST, str(exc))
                    return
                except json.JSONDecodeError:
                    self.write_error(HTTPStatus.BAD_REQUEST, "invalid json")
                    return
                self.write_json(received, status=HTTPStatus.ACCEPTED)
                return
            if not self.require_auth(path):
                return
            try:
                payload = self.read_json()
                if (
                    len(parts) == 5
                    and parts[:3] == ["v2", "internal", "tasks"]
                    and parts[4] == "execute"
                ):
                    try:
                        task = manager.v2.execute_task_now(unquote(parts[3]))
                    except KeyError:
                        self.write_error(HTTPStatus.NOT_FOUND, "task not found")
                        return
                    self.write_json(task, status=HTTPStatus.ACCEPTED)
                    return
                if len(parts) == 2 and parts[0] == "v2" and parts[1] == "tasks":
                    project_id = str(payload.get("project_id") or "project_default")
                    try:
                        project_allowed = manager.v2.can_access_project(
                            project_id,
                            self.principal_id(),
                            self.current_roles(),
                            write=True,
                        )
                    except KeyError:
                        self.write_error(HTTPStatus.BAD_REQUEST, "project not found")
                        return
                    if not project_allowed:
                        self.write_error(
                            HTTPStatus.FORBIDDEN, "project membership required"
                        )
                        return
                    try:
                        task = manager.v2.create_task(
                            payload,
                            principal=self.principal_id() or "api-token",
                            idempotency_key=self.headers.get("idempotency-key"),
                        )
                    except ValueError as exc:
                        self.write_error(HTTPStatus.BAD_REQUEST, str(exc))
                        return
                    self.write_json(task, status=HTTPStatus.CREATED)
                    return
                if (
                    len(parts) == 4
                    and parts[0] == "v2"
                    and parts[1] == "tasks"
                    and parts[3] == "messages"
                ):
                    if not self.authorize_v2_task(unquote(parts[2]), write=True):
                        return
                    try:
                        event = manager.v2.append_message(
                            unquote(parts[2]),
                            str(payload.get("message") or payload.get("prompt") or ""),
                            principal=self.principal_id(),
                        )
                    except KeyError:
                        self.write_error(HTTPStatus.NOT_FOUND, "task not found")
                        return
                    except ValueError as exc:
                        self.write_error(HTTPStatus.BAD_REQUEST, str(exc))
                        return
                    self.write_json({"event": event}, status=HTTPStatus.ACCEPTED)
                    return
                if (
                    len(parts) == 4
                    and parts[0] == "v2"
                    and parts[1] == "tasks"
                    and parts[3] == "retry"
                ):
                    if not self.authorize_v2_task(unquote(parts[2]), write=True):
                        return
                    try:
                        task = manager.v2.retry_task(
                            unquote(parts[2]),
                            principal=self.principal_id(),
                        )
                    except KeyError:
                        self.write_error(HTTPStatus.NOT_FOUND, "task not found")
                        return
                    except ValueError as exc:
                        self.write_error(HTTPStatus.BAD_REQUEST, str(exc))
                        return
                    self.write_json(task, status=HTTPStatus.ACCEPTED)
                    return
                if (
                    len(parts) == 4
                    and parts[0] == "v2"
                    and parts[1] == "tasks"
                    and parts[3] == "replay"
                ):
                    if not self.authorize_v2_task(unquote(parts[2]), write=True):
                        return
                    try:
                        replay = manager.v2.replay_task(
                            unquote(parts[2]),
                            principal=self.principal_id(),
                        )
                    except KeyError:
                        self.write_error(HTTPStatus.NOT_FOUND, "task not found")
                        return
                    self.write_json(replay, status=HTTPStatus.CREATED)
                    return
                if (
                    len(parts) == 3
                    and parts[0] == "v2"
                    and parts[1] == "admin"
                    and parts[2] == "execution-units"
                ):
                    try:
                        unit = manager.v2.register_execution_unit(payload)
                    except ValueError as exc:
                        self.write_error(HTTPStatus.BAD_REQUEST, str(exc))
                        return
                    self.write_json(unit, status=HTTPStatus.CREATED)
                    return
                if (
                    len(parts) == 4
                    and parts[0] == "v2"
                    and parts[1] == "admin"
                    and parts[2] == "execution-units"
                    and parts[3] == "discover"
                ):
                    self.write_json(manager.v2.discover_execution_units())
                    return
                if (
                    len(parts) == 5
                    and parts[0] == "v2"
                    and parts[1] == "admin"
                    and parts[2] == "channels"
                    and parts[4] == "config"
                ):
                    channel = manager.v2.configure_channel(unquote(parts[3]), payload)
                    self.write_json(channel, status=HTTPStatus.ACCEPTED)
                    return
                if (
                    len(parts) == 5
                    and parts[0] == "v2"
                    and parts[1] == "admin"
                    and parts[2] == "channels"
                    and parts[4] == "send"
                ):
                    message = manager.v2.send_channel_message(unquote(parts[3]), payload)
                    self.write_json(message, status=HTTPStatus.ACCEPTED)
                    return
                if (
                    len(parts) == 3
                    and parts[0] == "v2"
                    and parts[1] == "admin"
                    and parts[2] == "tenants"
                ):
                    tenant = manager.v2.upsert_tenant(
                        payload,
                        principal=self.principal_id() or "api-token",
                    )
                    self.write_json(tenant, status=HTTPStatus.CREATED)
                    return
                if parts == ["v2", "admin", "projects"]:
                    project = manager.v2.upsert_project(
                        payload,
                        principal=self.principal_id() or "api-token",
                    )
                    self.write_json(project, status=HTTPStatus.CREATED)
                    return
                if (
                    len(parts) == 5
                    and parts[:3] == ["v2", "admin", "projects"]
                    and parts[4] == "members"
                ):
                    try:
                        member = manager.v2.upsert_project_member(
                            unquote(parts[3]), payload
                        )
                    except KeyError:
                        self.write_error(HTTPStatus.NOT_FOUND, "project not found")
                        return
                    self.write_json(member, status=HTTPStatus.CREATED)
                    return
                if (
                    len(parts) == 5
                    and parts[0] == "v2"
                    and parts[1] == "admin"
                    and parts[2] == "tenants"
                    and parts[4] == "users"
                ):
                    user = manager.v2.upsert_tenant_user(unquote(parts[3]), payload)
                    self.write_json(user, status=HTTPStatus.CREATED)
                    return
                if (
                    len(parts) == 5
                    and parts[0] == "v2"
                    and parts[1] == "admin"
                    and parts[2] == "tenants"
                    and parts[4] == "rbac"
                ):
                    policy = manager.v2.upsert_rbac_policy(unquote(parts[3]), payload)
                    self.write_json(policy, status=HTTPStatus.CREATED)
                    return
                if path == "/acp":
                    response, status = handle_acp_jsonrpc(manager, payload)
                    self.write_json(response, status=status)
                    return
                if len(parts) == 1 and parts[0] == "cleanup":
                    self.write_json({"cleanup": manager.cleanup_once()})
                    return
                if len(parts) == 2 and parts[0] == "ops" and parts[1] == "backups":
                    self.write_json({"backup": manager.create_backup()}, status=HTTPStatus.CREATED)
                    return
                if len(parts) == 2 and parts[0] == "ops" and parts[1] == "drills":
                    self.write_json(manager.run_drills())
                    return
                if len(parts) == 2 and parts[0] == "access" and parts[1] == "projects":
                    project = manager.create_access_project(payload)
                    self.write_json(project, status=HTTPStatus.CREATED)
                    return
                if len(parts) == 2 and parts[0] == "access" and parts[1] == "tokens":
                    token = manager.create_api_token(
                        payload,
                        headers=self.headers,
                        principal=self.principal_id(),
                    )
                    self.write_json(token, status=HTTPStatus.CREATED)
                    return
                if len(parts) == 2 and parts[0] == "auth" and parts[1] == "users":
                    user = self.create_auth_user(payload)
                    self.write_json(user, status=HTTPStatus.CREATED)
                    return
                if len(parts) == 4 and parts[0] == "auth" and parts[1] == "users":
                    try:
                        user = self.manage_auth_user(unquote(parts[2]), parts[3], payload)
                    except KeyError:
                        self.write_error(HTTPStatus.NOT_FOUND, "user not found")
                        return
                    self.write_json(user, status=HTTPStatus.ACCEPTED)
                    return
                if len(parts) == 2 and parts[0] == "workers" and parts[1] == "registrations":
                    registration = manager.create_worker_registration(payload)
                    self.write_json(registration, status=HTTPStatus.CREATED)
                    return
                if len(parts) == 3 and parts[0] == "workers" and parts[2] == "heartbeat":
                    worker = manager.remote_worker_heartbeat(unquote(parts[1]), payload)
                    self.write_json({"worker": worker}, status=HTTPStatus.ACCEPTED)
                    return
                if len(parts) == 3 and parts[0] == "workers" and parts[2] == "claim":
                    claim = manager.claim_remote_run(unquote(parts[1]), payload)
                    self.write_json(claim, status=HTTPStatus.ACCEPTED)
                    return
                if len(parts) == 3 and parts[0] == "workers" and parts[2] == "drain":
                    result = manager.drain_worker(unquote(parts[1]), payload.get("reason"))
                    self.write_json(result, status=HTTPStatus.ACCEPTED)
                    return
                if len(parts) == 3 and parts[0] == "workers" and parts[2] == "resume":
                    result = manager.resume_worker(unquote(parts[1]))
                    self.write_json(result, status=HTTPStatus.ACCEPTED)
                    return
                if len(parts) == 3 and parts[0] == "workers" and parts[2] == "retry":
                    result = manager.retry_worker_runs(unquote(parts[1]), payload.get("reason"))
                    self.write_json(result, status=HTTPStatus.ACCEPTED)
                    return
                if (
                    len(parts) == 5
                    and parts[0] == "workers"
                    and parts[2] == "runs"
                    and parts[4] == "events"
                ):
                    event = manager.append_remote_worker_event(
                        unquote(parts[1]),
                        unquote(parts[3]),
                        payload,
                    )
                    self.write_json({"event": event}, status=HTTPStatus.ACCEPTED)
                    return
                if (
                    len(parts) == 5
                    and parts[0] == "workers"
                    and parts[2] == "runs"
                    and parts[4] == "artifacts"
                ):
                    artifact = manager.write_remote_worker_artifact(
                        unquote(parts[1]),
                        unquote(parts[3]),
                        payload,
                    )
                    self.write_json(artifact, status=HTTPStatus.CREATED)
                    return
                if (
                    len(parts) == 4
                    and parts[0] == "access"
                    and parts[1] == "tokens"
                    and parts[3] == "revoke"
                ):
                    token = manager.revoke_api_token(parts[2])
                    self.write_json(token, status=HTTPStatus.ACCEPTED)
                    return
                if len(parts) == 1 and parts[0] == "profiles":
                    profile = manager.create_profile(payload)
                    self.write_json(profile, status=HTTPStatus.CREATED)
                    return
                if len(parts) == 1 and parts[0] == "missions":
                    mission = manager.create_mission(payload)
                    self.write_json(mission, status=HTTPStatus.CREATED)
                    return
                if len(parts) == 1 and parts[0] == "tasks":
                    task = manager.create_task(payload, access_context=self.access_context())
                    self.write_json(task, status=HTTPStatus.CREATED)
                    return
                if len(parts) == 3 and parts[0] == "tasks" and parts[2] == "cancel":
                    try:
                        task = manager.cancel_task(
                            unquote(parts[1]),
                            payload.get("reason"),
                            access_context=self.access_context(),
                        )
                    except KeyError:
                        self.write_error(HTTPStatus.NOT_FOUND, "task not found")
                        return
                    self.write_json(task, status=HTTPStatus.ACCEPTED)
                    return
                if len(parts) == 3 and parts[0] == "tasks" and parts[2] == "messages":
                    message = payload.get("message") or payload.get("prompt")
                    if not isinstance(message, str) or not message.strip():
                        self.write_error(HTTPStatus.BAD_REQUEST, "message is required")
                        return
                    try:
                        accepted = manager.send_task_message(
                            unquote(parts[1]),
                            message,
                            access_context=self.access_context(),
                        )
                    except KeyError:
                        self.write_error(HTTPStatus.NOT_FOUND, "task not found")
                        return
                    self.write_json(accepted, status=HTTPStatus.ACCEPTED)
                    return
                if len(parts) == 2 and parts[0] == "a2a" and parts[1] == "tasks":
                    task = create_a2a_task(manager, payload)
                    self.write_json(task, status=HTTPStatus.CREATED)
                    return
                if len(parts) == 3 and parts[0] == "missions" and parts[2] == "cancel":
                    try:
                        mission = manager.cancel_mission(parts[1], payload.get("reason"))
                    except KeyError:
                        self.write_error(HTTPStatus.NOT_FOUND, "mission not found")
                        return
                    self.write_json(mission, status=HTTPStatus.ACCEPTED)
                    return
                if (
                    len(parts) == 4
                    and parts[0] == "missions"
                    and parts[2] == "review-gate"
                    and parts[3] == "override"
                ):
                    try:
                        mission = manager.override_review_gate(parts[1], payload)
                    except KeyError:
                        self.write_error(HTTPStatus.NOT_FOUND, "mission not found")
                        return
                    self.write_json(mission, status=HTTPStatus.ACCEPTED)
                    return
                if len(parts) == 1 and parts[0] == "runs":
                    spec = RunSpec.from_payload(payload)
                    run = manager.create_run(spec)
                    self.write_json(run.to_dict(), status=HTTPStatus.CREATED)
                    return
                if len(parts) == 1 and parts[0] == "session":
                    run_id = payload.get("run_id") or payload.get("session_id")
                    if isinstance(run_id, str) and run_id.strip():
                        run = manager.get_run(run_id.strip())
                        if run is None:
                            self.write_error(HTTPStatus.NOT_FOUND, "session not found")
                            return
                    else:
                        spec = RunSpec.from_payload(payload)
                        run = manager.create_run(spec)
                    self.write_json(
                        {
                            "session": {
                                "id": run.run_id,
                                "run_id": run.run_id,
                                "events": f"/session/{run.run_id}/events",
                            },
                            "run": run.to_dict(),
                        },
                        status=HTTPStatus.CREATED,
                    )
                    return
                if len(parts) == 3 and parts[0] == "runs" and parts[2] == "input":
                    prompt = payload.get("prompt")
                    if not isinstance(prompt, str) or not prompt.strip():
                        self.write_error(HTTPStatus.BAD_REQUEST, "prompt is required")
                        return
                    manager.send_input(parts[1], prompt)
                    self.write_json(
                        {"accepted": True, "run_id": parts[1]},
                        status=HTTPStatus.ACCEPTED,
                    )
                    return
                if len(parts) == 3 and parts[0] == "session" and parts[2] == "prompt":
                    prompt = payload.get("prompt") or payload.get("message")
                    if not isinstance(prompt, str) or not prompt.strip():
                        self.write_error(HTTPStatus.BAD_REQUEST, "prompt is required")
                        return
                    manager.send_input(parts[1], prompt)
                    self.write_json(
                        {"accepted": True, "session_id": parts[1], "run_id": parts[1]},
                        status=HTTPStatus.ACCEPTED,
                    )
                    return
                if len(parts) == 3 and parts[0] == "runs" and parts[2] == "cancel":
                    manager.cancel(parts[1], payload.get("reason"))
                    self.write_json(
                        {"cancelled": True, "run_id": parts[1]},
                        status=HTTPStatus.ACCEPTED,
                    )
                    return
                if len(parts) == 3 and parts[0] == "session" and parts[2] == "cancel":
                    manager.cancel(parts[1], payload.get("reason"))
                    self.write_json(
                        {"cancelled": True, "session_id": parts[1], "run_id": parts[1]},
                        status=HTTPStatus.ACCEPTED,
                    )
                    return
                if (
                    len(parts) == 6
                    and parts[0] == "runs"
                    and parts[2] == "permissions"
                    and parts[4] == "notifications"
                    and parts[5] == "retry"
                ):
                    notifications = manager.retry_permission_notifications(parts[1], parts[3])
                    self.write_json(
                        {"notifications": notifications},
                        status=HTTPStatus.ACCEPTED,
                    )
                    return
                if (
                    len(parts) == 4
                    and parts[0] == "runs"
                    and parts[2] == "permissions"
                    and parts[3]
                ):
                    manager.resolve_permission(parts[1], parts[3], payload)
                    self.write_json(
                        {"accepted": True, "run_id": parts[1], "permission_id": parts[3]},
                        status=HTTPStatus.ACCEPTED,
                    )
                    return
                if (
                    len(parts) == 4
                    and parts[0] == "session"
                    and parts[2] == "permission"
                    and parts[3]
                ):
                    manager.resolve_permission(parts[1], parts[3], payload)
                    self.write_json(
                        {
                            "accepted": True,
                            "session_id": parts[1],
                            "run_id": parts[1],
                            "permission_id": parts[3],
                        },
                        status=HTTPStatus.ACCEPTED,
                    )
                    return
            except KeyError:
                self.write_error(HTTPStatus.NOT_FOUND, "run not found")
                return
            except ValueError as exc:
                self.write_error(HTTPStatus.BAD_REQUEST, str(exc))
                return
            except RuntimeError as exc:
                self.write_error(HTTPStatus.BAD_GATEWAY, str(exc))
                return
            except PermissionError as exc:
                self.write_error(HTTPStatus.FORBIDDEN, str(exc))
                return
            except json.JSONDecodeError:
                self.write_error(HTTPStatus.BAD_REQUEST, "invalid json")
                return
            self.write_error(HTTPStatus.NOT_FOUND, "not found")

        def stream_events(self, run_id: str) -> None:
            if manager.get_run(run_id) is None:
                self.write_error(HTTPStatus.NOT_FOUND, "run not found")
                return

            last_sequence = parse_last_event_id(self.headers.get("Last-Event-ID"))
            last_sequence = manager.store.record_gap_if_needed(run_id, last_sequence)
            self.send_response(HTTPStatus.OK)
            self.send_header("content-type", "text/event-stream; charset=utf-8")
            self.send_header("cache-control", "no-cache")
            self.send_header("connection", "close")
            self.end_headers()
            self.close_connection = True

            last_heartbeat = time.monotonic()
            try:
                while True:
                    events = manager.store.wait_for_events(run_id, last_sequence, timeout=1.0)
                    for event in events:
                        self.write_sse(event.sequence, event.type, event.to_dict())
                        last_sequence = event.sequence
                    if manager.store.is_terminal(run_id) and not events:
                        break
                    if time.monotonic() - last_heartbeat >= 10:
                        self.wfile.write(b": heartbeat\n\n")
                        self.wfile.flush()
                        last_heartbeat = time.monotonic()
            except (BrokenPipeError, ConnectionResetError):
                return

        def stream_session_events(self, session_id: str) -> None:
            run = manager.get_run(session_id)
            if run is None:
                self.write_error(HTTPStatus.NOT_FOUND, "session not found")
                return

            last_sequence = parse_last_event_id(self.headers.get("Last-Event-ID"))
            last_sequence = manager.store.record_gap_if_needed(session_id, last_sequence)
            self.send_response(HTTPStatus.OK)
            self.send_header("content-type", "text/event-stream; charset=utf-8")
            self.send_header("cache-control", "no-cache")
            self.send_header("connection", "close")
            self.end_headers()
            self.close_connection = True

            last_heartbeat = time.monotonic()
            try:
                while True:
                    events = manager.store.wait_for_events(session_id, last_sequence, timeout=1.0)
                    for event in events:
                        projected = project_event(event, source_adapter=run.spec.adapter)
                        self.write_sse(projected["id"], projected["type"], projected)
                        last_sequence = event.sequence
                    if manager.store.is_terminal(session_id) and not events:
                        self.cache_projected_session_events(session_id)
                        break
                    if time.monotonic() - last_heartbeat >= 10:
                        self.wfile.write(b": heartbeat\n\n")
                        self.wfile.flush()
                        last_heartbeat = time.monotonic()
            except (BrokenPipeError, ConnectionResetError):
                return

        def stream_v2_webshell_events(self, task_id: str) -> None:
            if not self.authorize_v2_task(task_id):
                return
            try:
                manager.v2.get_task(task_id)
            except KeyError:
                self.write_error(HTTPStatus.NOT_FOUND, "task not found")
                return

            last_sequence = parse_last_event_id(self.headers.get("Last-Event-ID"))
            self.send_response(HTTPStatus.OK)
            self.send_header("content-type", "text/event-stream; charset=utf-8")
            self.send_header("cache-control", "no-cache")
            self.send_header("connection", "close")
            self.end_headers()
            self.close_connection = True

            last_heartbeat = time.monotonic()
            try:
                while True:
                    events = manager.v2.events(task_id, after=last_sequence)
                    for event in events:
                        last_sequence = event["sequence"]
                        if event["type"] not in {
                            "task.created",
                            "user.message",
                            "agent.message",
                            "task.completed",
                        }:
                            continue
                        projected = v2_event_to_daemon_event(event)
                        self.write_sse(projected["id"], "message", projected)
                    current = manager.v2.get_task(task_id)
                    if current["status"] in {"completed", "failed", "cancelled"} and not events:
                        break
                    if time.monotonic() - last_heartbeat >= 10:
                        self.wfile.write(b": heartbeat\n\n")
                        self.wfile.flush()
                        last_heartbeat = time.monotonic()
                    time.sleep(0.2)
            except (BrokenPipeError, ConnectionResetError):
                return

        def projected_session_events(self, session_id: str) -> list[dict[str, Any]]:
            run = manager.get_run(session_id)
            if run is None:
                raise KeyError(session_id)
            projected = project_events(
                manager.store.events_since(session_id),
                source_adapter=run.spec.adapter,
            )
            self.write_projected_session_cache(session_id, projected)
            return projected

        def cache_projected_session_events(self, session_id: str) -> None:
            try:
                self.projected_session_events(session_id)
            except KeyError:
                return

        def write_projected_session_cache(
            self, session_id: str, projected: list[dict[str, Any]]
        ) -> None:
            lines = "\n".join(
                json.dumps(event, ensure_ascii=False, sort_keys=True) for event in projected
            )
            if lines:
                lines += "\n"
            manager.store.write_text(session_id, "ui_daemon_events.jsonl", lines)

        def require_auth(self, path: str) -> bool:
            self.current_identity = None
            session_identity = self.session_identity()
            if session_identity:
                self.current_identity = session_identity
                required_scope = required_scope_for(self.command, path)
                if required_scope is None or roles_allow(
                    session_identity.get("roles"),
                    required_scope,
                ):
                    return True
                self.write_json(
                    {
                        "error": "forbidden",
                        "required_scope": required_scope,
                    },
                    status=HTTPStatus.FORBIDDEN,
                )
                return False
            if is_authorized(auth_config, path, self.headers.get("authorization")):
                return True
            identity = None
            if auth_config.enabled:
                identity = manager.access.authenticate_bearer(
                    self.headers.get("authorization")
                )
            if identity:
                self.current_identity = identity
                required_scope = required_scope_for(self.command, path)
                if required_scope is None or scopes_allow(identity["scopes"], required_scope):
                    return True
                self.write_json(
                    {
                        "error": "forbidden",
                        "required_scope": required_scope,
                    },
                    status=HTTPStatus.FORBIDDEN,
                )
                return False
            self.write_json(
                {"error": "unauthorized"},
                status=HTTPStatus.UNAUTHORIZED,
                headers={"www-authenticate": "Bearer"},
            )
            return False

        def handle_login(self) -> None:
            try:
                payload = self.read_json()
            except (json.JSONDecodeError, ValueError):
                self.write_error(HTTPStatus.BAD_REQUEST, "invalid login payload")
                return
            username = payload.get("username")
            email = payload.get("email") or username
            password = payload.get("password")
            if not auth_config.login_enabled:
                self.write_json(auth_config.session_status(None))
                return
            login_email = auth_config.resolve_login_email(email)
            if login_email is None:
                self.record_login_failure("unknown")
                self.write_json(
                    {"error": "invalid credentials"},
                    status=HTTPStatus.UNAUTHORIZED,
                )
                return
            throttle_key = f"{self.client_ip()}:{login_email}"
            if self.login_limited(throttle_key):
                self.write_json(
                    {"error": "too many login attempts"},
                    status=HTTPStatus.TOO_MANY_REQUESTS,
                )
                return
            user = manager.store.get_auth_user(login_email)
            if (
                user is None
                or user.status != "active"
                or not verify_password(password, user.password_hash)
            ):
                self.record_login_failure(throttle_key)
                self.write_json(
                    {"error": "invalid credentials"},
                    status=HTTPStatus.UNAUTHORIZED,
                )
                return
            login_failures.pop(throttle_key, None)
            _, session_token = manager.store.create_auth_session(
                user=user,
                ttl_seconds=auth_config.session_ttl_seconds,
                user_agent=self.headers.get("user-agent"),
                ip_address=self.client_ip(),
            )
            identity = manager.store.auth_session_identity(session_token)
            self.write_json(
                auth_config.session_status(identity),
                headers={
                    "set-cookie": auth_config.issue_session_cookie(
                        session_token,
                        cookie_path=self.cookie_path(),
                        secure=self.is_secure_request(),
                    )
                },
            )

        def create_auth_user(self, payload: dict[str, Any]) -> dict[str, Any]:
            email = payload.get("email")
            password = payload.get("password")
            if not isinstance(email, str) or not isinstance(password, str) or not password:
                raise ValueError("email and password are required")
            roles = validate_auth_roles(payload.get("roles") or ["member"])
            user = manager.store.create_auth_user(
                email=email,
                display_name=str(payload.get("display_name") or email),
                password_hash=hash_password(password),
                roles=list(roles),
                email_verified=bool(payload.get("email_verified")),
            )
            return user.to_dict()

        def manage_auth_user(
            self,
            email: str,
            action: str,
            payload: dict[str, Any],
        ) -> dict[str, Any]:
            if action == "roles":
                roles = validate_auth_roles(payload.get("roles"))
                if email == self.principal_id() and "owner" not in roles:
                    raise ValueError("cannot remove owner from current user")
                return manager.store.update_auth_user(email, roles=list(roles)).to_dict()
            if action == "status":
                status = payload.get("status")
                if status not in {"active", "disabled"}:
                    raise ValueError("status must be active or disabled")
                if email == self.principal_id() and status != "active":
                    raise ValueError("cannot disable current user")
                user = manager.store.update_auth_user(email, status=str(status))
                if status != "active":
                    manager.store.revoke_auth_user_sessions(email)
                return user.to_dict()
            if action == "password":
                password = payload.get("password")
                if not isinstance(password, str) or not password:
                    raise ValueError("password is required")
                user = manager.store.reset_auth_user_password(email, hash_password(password))
                manager.store.revoke_auth_user_sessions(email)
                return user.to_dict()
            raise KeyError(action)

        def principal_id(self) -> str | None:
            if self.current_identity:
                principal = self.current_identity.get("principal_id")
                return str(principal) if principal else None
            remote_user = self.headers.get("x-remote-user")
            if remote_user:
                return remote_user
            authorization = self.headers.get("authorization") or ""
            if authorization.strip():
                return "api-token"
            return None

        def authorize_v2_task(self, task_id: str, *, write: bool = False) -> bool:
            try:
                allowed = manager.v2.can_access_task(
                    task_id,
                    self.principal_id(),
                    self.current_roles(),
                    write=write,
                )
            except KeyError:
                self.write_error(HTTPStatus.NOT_FOUND, "task not found")
                return False
            if not allowed:
                self.write_error(HTTPStatus.FORBIDDEN, "project membership required")
                return False
            return True

        def current_roles(self) -> list[str] | None:
            if not self.current_identity:
                return None
            roles = self.current_identity.get("roles")
            if not isinstance(roles, list):
                return None
            return [role for role in roles if isinstance(role, str)]

        def access_context(self) -> dict[str, Any] | None:
            if not self.current_identity:
                return None
            context = dict(self.current_identity)
            if "principal_id" not in context and context.get("email"):
                context["principal_id"] = context["email"]
            return context

        def cookie_path(self) -> str:
            prefix = self.headers.get("x-forwarded-prefix", "").strip().rstrip("/")
            if prefix.startswith("/"):
                return prefix
            return "/"

        def is_secure_request(self) -> bool:
            return self.headers.get("x-forwarded-proto", "").lower() == "https"

        def client_ip(self) -> str:
            forwarded_for = self.headers.get("x-forwarded-for", "")
            if forwarded_for:
                return forwarded_for.split(",", 1)[0].strip()
            return str(self.client_address[0])

        def session_identity(self) -> dict[str, Any] | None:
            return manager.store.auth_session_identity(
                auth_config.session_token(self.headers.get("cookie"))
            )

        def login_limited(self, key: str) -> bool:
            now = time.time()
            window_start = now - 10 * 60
            attempts = [
                timestamp
                for timestamp in login_failures.get(key, [])
                if timestamp >= window_start
            ]
            login_failures[key] = attempts
            return len(attempts) >= 5

        def record_login_failure(self, key: str) -> None:
            now = time.time()
            window_start = now - 10 * 60
            attempts = [
                timestamp
                for timestamp in login_failures.get(key, [])
                if timestamp >= window_start
            ]
            attempts.append(now)
            login_failures[key] = attempts

        def read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("content-length", "0") or "0")
            if length == 0:
                return {}
            body = self.rfile.read(length)
            payload = json.loads(body.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("json object required")
            return payload

        def write_json(
            self,
            payload: dict[str, Any],
            status: HTTPStatus = HTTPStatus.OK,
            headers: dict[str, str] | None = None,
        ) -> None:
            body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
            self.send_response(status)
            self.send_header("content-type", "application/json; charset=utf-8")
            self.send_header("content-length", str(len(body)))
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()
            self.close_connection = True

        def write_html(self, html: str, status: HTTPStatus = HTTPStatus.OK) -> None:
            body = html.encode("utf-8")
            self.send_response(status)
            self.send_header("content-type", "text/html; charset=utf-8")
            self.send_header("content-length", str(len(body)))
            self.send_header("cache-control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()
            self.close_connection = True

        def write_redirect(self, location: str) -> None:
            body = b""
            self.send_response(HTTPStatus.FOUND)
            self.send_header("location", location)
            self.send_header("content-length", "0")
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()
            self.close_connection = True

        def write_file(self, path: Path) -> None:
            body = path.read_bytes()
            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            self.send_response(HTTPStatus.OK)
            self.send_header("content-type", content_type)
            self.send_header("content-length", str(len(body)))
            self.send_header(
                "content-disposition",
                f'attachment; filename="{path.name.replace(chr(34), "")}"',
            )
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()
            self.close_connection = True

        def write_static_file(self, path: Path) -> None:
            body = path.read_bytes()
            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            self.send_response(HTTPStatus.OK)
            self.send_header("content-type", content_type)
            self.send_header("content-length", str(len(body)))
            self.send_header("cache-control", "public, max-age=31536000, immutable")
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()
            self.close_connection = True

        def base_url(self) -> str:
            host = self.headers.get("host")
            if host:
                return f"http://{host}"
            server_host, server_port = self.server.server_address[:2]
            return f"http://{server_host}:{server_port}"

        def write_error(self, status: HTTPStatus, message: str) -> None:
            self.write_json({"error": message}, status=status)

        def write_sse(self, event_id: int, event_type: str, payload: dict[str, Any]) -> None:
            data = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            frame = f"id: {event_id}\nevent: {event_type}\ndata: {data}\n\n"
            self.wfile.write(frame.encode("utf-8"))
            self.wfile.flush()

        def log_message(self, fmt: str, *args: Any) -> None:
            sys.stderr.write(
                "%s - - [%s] %s\n"
                % (self.address_string(), self.log_date_time_string(), fmt % args)
            )

    return RuntimeHandler


def split_path(path: str) -> list[str]:
    return [part for part in path.strip("/").split("/") if part]


def spa_redirect_target(path: str, headers: Any) -> str | None:
    if not request_prefers_html(headers):
        return None
    parts = split_path(path)
    if not parts:
        return None
    hash_path: str | None = None
    if (
        parts[0]
        in {"workspace", "overview", "units", "executors", "profiles", "access", "operations", "v2"}
        and len(parts) == 1
    ):
        hash_path = f"/{parts[0]}"
    elif parts[0] == "v2" and len(parts) == 2 and parts[1] == "admin":
        hash_path = "/v2/admin"
    elif parts[0] == "v2" and len(parts) == 3 and parts[1] == "tasks":
        hash_path = "/" + "/".join(parts)
    elif parts[0] in {"runs", "missions", "tasks"} and len(parts) <= 2:
        hash_path = "/" + "/".join(parts)
    if not hash_path:
        return None
    prefix = ""
    try:
        forwarded_prefix = headers.get("x-forwarded-prefix", "")
    except AttributeError:
        forwarded_prefix = ""
    forwarded_prefix = str(forwarded_prefix).strip().rstrip("/")
    if forwarded_prefix.startswith("/"):
        prefix = forwarded_prefix
    return f"{prefix}/#{hash_path}"


def request_prefers_html(headers: Any) -> bool:
    try:
        accept = str(headers.get("accept", ""))
    except AttributeError:
        return False
    if not accept:
        return False
    return "text/html" in accept.lower()


def parse_last_event_id(value: str | None) -> int:
    if not value:
        return 0
    try:
        return max(0, int(value))
    except ValueError:
        return 0


def required_scope_for(method: str, path: str) -> str | None:
    parts = split_path(path)
    method = method.upper()
    if path in {"/", "/ui", "/capabilities", "/acp", "/.well-known/agent-card.json"}:
        return None
    if parts and parts[0] == "assets":
        return None
    if not parts:
        return None
    if parts[0] == "auth":
        return "access:read" if method == "GET" else "access:write"
    if parts[0] == "v2":
        if len(parts) >= 2 and parts[1] == "admin":
            return "access:read" if method == "GET" else "access:write"
        if method == "GET":
            if len(parts) >= 4 and parts[3] in {"artifacts", "audit.json"}:
                return "artifacts:read"
            if len(parts) >= 4 and parts[3] == "events.json":
                return "events:read"
            if len(parts) >= 5 and parts[3] == "webshell":
                return "events:read"
            if len(parts) >= 4 and parts[3] in {"evaluations", "replays", "workflow"}:
                return "events:read"
            return "tasks:read"
        if len(parts) >= 4 and parts[3] in {"messages", "retry", "replay"}:
            return "tasks:write"
        return "tasks:create"
    if parts[0] == "workers":
        return "workers:read" if method == "GET" else "workers:write"
    if parts[0] == "permissions":
        return "permissions:read" if method == "GET" else "permissions:resolve"
    if parts[0] == "access":
        return "access:read" if method == "GET" else "access:write"
    if parts[0] in {"ops", "cleanup"}:
        return "ops:read" if method == "GET" else "ops:write"
    if parts[0] == "cost":
        return "cost:read"
    if parts[0] == "executors":
        return "executors:read"
    if parts[0] == "profiles":
        return "profiles:read" if method == "GET" else "profiles:write"
    if parts[0] in {"missions", "a2a", "temporal"}:
        return "missions:read" if method == "GET" else "missions:write"
    if parts[0] == "tasks":
        if method == "GET":
            if len(parts) >= 3 and parts[2] == "artifacts":
                return "artifacts:read"
            if len(parts) >= 3 and parts[2] in {"events.json", "result"}:
                return "events:read"
            return "tasks:read"
        if len(parts) >= 3 and parts[2] == "cancel":
            return "tasks:cancel"
        if len(parts) >= 3 and parts[2] == "messages":
            return "tasks:write"
        return "tasks:create"
    if parts[0] == "session":
        if method == "GET":
            if len(parts) >= 3 and parts[2] in {"events", "events.json"}:
                return "events:read"
            return "runs:read"
        if len(parts) >= 3 and parts[2] == "cancel":
            return "runs:cancel"
        if len(parts) >= 3 and parts[2] == "permission":
            return "permissions:resolve"
        return "runs:create"
    if parts[0] == "runs":
        if method == "GET":
            if len(parts) >= 3 and parts[2] == "artifacts":
                return "artifacts:read"
            if len(parts) >= 3 and parts[2] == "permission-notifications":
                return "permissions:read"
            if len(parts) >= 3 and parts[2] in {"events", "events.json", "audit.json"}:
                return "events:read"
            return "runs:read"
        if len(parts) >= 3 and parts[2] == "cancel":
            return "runs:cancel"
        if len(parts) >= 3 and parts[2] == "permissions":
            return "permissions:resolve"
        return "runs:create"
    if parts[0] == "p5":
        return "ops:read"
    return None


def validate_auth_roles(roles: Any) -> list[str]:
    if not isinstance(roles, list) or not roles:
        raise ValueError("roles must be a non-empty list of strings")
    if not all(isinstance(role, str) for role in roles):
        raise ValueError("roles must be a non-empty list of strings")
    allowed_roles = {"owner", "operator", "auditor", "member"}
    normalized_roles: list[str] = []
    for role in roles:
        normalized_role = role.strip()
        if normalized_role not in allowed_roles:
            raise ValueError("roles may only contain owner, operator, auditor, or member")
        if normalized_role not in normalized_roles:
            normalized_roles.append(normalized_role)
    return normalized_roles


def load_index_html() -> str:
    path = Path(__file__).with_name("static") / "index.html"
    return path.read_text(encoding="utf-8")


def resolve_static_path(path: str) -> Path | None:
    static_root = Path(__file__).with_name("static").resolve()
    relative = path.lstrip("/")
    if not relative or relative.startswith((".", "/")):
        return None
    candidate = (static_root / relative).resolve()
    if static_root not in candidate.parents or not candidate.is_file():
        return None
    return candidate


def build_server(
    host: str,
    port: int,
    artifact_root: Path,
    auth_config: AuthConfig | None = None,
    qwen_base_url: str | None = None,
    qwen_token: str | None = None,
    worker_capacity: int | None = None,
    worker_id: str | None = None,
    lease_ttl_seconds: int | None = None,
) -> ThreadingHTTPServer:
    manager = RunManager(
        artifact_root=artifact_root,
        qwen_base_url=qwen_base_url,
        qwen_token=qwen_token,
        worker_capacity=worker_capacity,
        worker_id=worker_id,
        lease_ttl_seconds=lease_ttl_seconds,
        heartbeat_enabled=True,
    )
    return RuntimeHTTPServer((host, port), make_handler(manager, auth_config=auth_config), manager)


class RuntimeHTTPServer(ThreadingHTTPServer):
    def __init__(
        self,
        server_address: tuple[str, int],
        handler_class: type[BaseHTTPRequestHandler],
        manager: RunManager,
    ):
        super().__init__(server_address, handler_class)
        self.manager = manager

    def server_close(self) -> None:
        self.manager.shutdown()
        super().server_close()


def parse_optional_int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError:
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AgentFlow Runtime POC")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=Path("runtime/artifacts"),
        help="directory for run artifacts",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("RUN_MANAGER_TOKEN"),
        help="bearer token for Run Manager API; defaults to RUN_MANAGER_TOKEN",
    )
    parser.add_argument(
        "--protect-health",
        action="store_true",
        default=os.environ.get("RUN_MANAGER_PROTECT_HEALTH") == "1",
        help="require bearer token for /health too",
    )
    parser.add_argument(
        "--login-user",
        default=os.environ.get("RUN_MANAGER_LOGIN_USER"),
        help="console login username; defaults to RUN_MANAGER_LOGIN_USER",
    )
    parser.add_argument(
        "--login-password",
        default=os.environ.get("RUN_MANAGER_LOGIN_PASSWORD"),
        help="console login password; defaults to RUN_MANAGER_LOGIN_PASSWORD",
    )
    parser.add_argument(
        "--bootstrap-email",
        default=os.environ.get("RUN_MANAGER_BOOTSTRAP_EMAIL"),
        help="bootstrap owner email; defaults to RUN_MANAGER_BOOTSTRAP_EMAIL",
    )
    parser.add_argument(
        "--bootstrap-password",
        default=os.environ.get("RUN_MANAGER_BOOTSTRAP_PASSWORD"),
        help="bootstrap owner password; defaults to RUN_MANAGER_BOOTSTRAP_PASSWORD",
    )
    parser.add_argument(
        "--bootstrap-name",
        default=os.environ.get("RUN_MANAGER_BOOTSTRAP_NAME"),
        help="bootstrap owner display name; defaults to RUN_MANAGER_BOOTSTRAP_NAME",
    )
    parser.add_argument(
        "--session-secret",
        default=os.environ.get("RUN_MANAGER_SESSION_SECRET"),
        help="secret used to sign console session cookies",
    )
    parser.add_argument(
        "--qwen-url",
        default=os.environ.get("QWEN_SERVE_URL"),
        help="existing qwen serve base URL",
    )
    parser.add_argument(
        "--qwen-token",
        default=os.environ.get("QWEN_SERVE_TOKEN"),
        help="bearer token for qwen serve",
    )
    parser.add_argument(
        "--worker-capacity",
        type=int,
        default=parse_optional_int(os.environ.get("RUN_MANAGER_WORKER_CAPACITY")),
        help="max concurrent SAEU runs for this local worker",
    )
    parser.add_argument(
        "--worker-id",
        default=os.environ.get("RUN_MANAGER_WORKER_ID"),
        help="stable id for this local worker heartbeat",
    )
    parser.add_argument(
        "--lease-ttl-seconds",
        type=int,
        default=parse_optional_int(os.environ.get("RUN_MANAGER_LEASE_TTL_SECONDS")),
        help="seconds before an unrefreshed run lease can be reclaimed",
    )
    args = parser.parse_args(argv)
    executor_config = ExecutorConfig.from_env()
    supervisor = None if executor_config.enabled else qwen_supervisor_from_env()
    if supervisor:
        supervisor.start()
    server = build_server(
        args.host,
        args.port,
        args.artifact_root,
        auth_config=AuthConfig(
            token=args.token,
            protect_health=args.protect_health,
            login_user=args.login_user,
            login_password=args.login_password,
            bootstrap_email=args.bootstrap_email,
            bootstrap_password=args.bootstrap_password,
            bootstrap_name=args.bootstrap_name,
            session_secret=args.session_secret,
        ),
        qwen_base_url=args.qwen_url,
        qwen_token=args.qwen_token,
        worker_capacity=args.worker_capacity,
        worker_id=args.worker_id,
        lease_ttl_seconds=args.lease_ttl_seconds,
    )
    print(f"cloud-agents-runtime listening on http://{args.host}:{args.port}")
    print(f"artifacts: {args.artifact_root}")
    if args.token:
        print("run manager auth: enabled")
    if args.qwen_url:
        print(f"qwen serve: {args.qwen_url}")
    print(f"executor registry: {server.manager.executor_registry.config.to_dict()}")
    print(f"worker capacity: {server.manager.worker_capacity}")
    print(f"resource limits: {server.manager.resource_resolver.config.to_dict()}")
    print(f"cleanup policy: {server.manager.cleanup_manager.policy.to_dict()}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down")
    finally:
        server.server_close()
        if supervisor:
            supervisor.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
