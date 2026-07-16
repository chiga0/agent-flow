from __future__ import annotations

import json
import re
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from runtime.cloud_agents_runtime.auth import AuthConfig
from runtime.cloud_agents_runtime.server import build_server, main as server_main


class RuntimeServerTest(unittest.TestCase):
    def test_runtime_main_help_builds_parser_defaults(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            server_main(["--help"])
        self.assertEqual(ctx.exception.code, 0)

    def test_auth_protects_run_routes_and_allows_health(self) -> None:
        with running_runtime(token="secret") as base_url:
            health = request_json(f"{base_url}/health")
            self.assertTrue(health["ok"])

            with self.assertRaises(urllib.error.HTTPError) as ctx:
                request_json(f"{base_url}/capabilities")
            self.assertEqual(ctx.exception.code, HTTPStatus.UNAUTHORIZED)

            capabilities = request_json(
                f"{base_url}/capabilities",
                headers={"authorization": "Bearer secret"},
            )
            self.assertIn("fake", capabilities["adapters"])
            self.assertIn("default_cpus", capabilities["resource_limits"])
            self.assertIn("workspace_retention_seconds", capabilities["cleanup_policy"])
            self.assertIn("acp_jsonrpc_poc", capabilities["features"])
            self.assertIn("a2a_gateway_poc", capabilities["features"])
            self.assertIn("temporal_workflow_plan_poc", capabilities["features"])
            self.assertIn("daemon_event_projection", capabilities["features"])
            self.assertIn("session_events", capabilities["features"])
            self.assertIn("webshell_compatible_bff", capabilities["features"])
            self.assertIn("task_workspace_bff", capabilities["features"])
            self.assertEqual(
                capabilities["ui_projection"]["routes"]["events"],
                "/session/{id}/events",
            )
            self.assertEqual(
                capabilities["task_workspace"]["routes"]["create_task"],
                "/tasks",
            )
            queue = request_json(
                f"{base_url}/queue",
                headers={"authorization": "Bearer secret"},
            )
            self.assertIn("workers", queue)
            workers = request_json(
                f"{base_url}/workers",
                headers={"authorization": "Bearer secret"},
            )
            self.assertGreaterEqual(workers["workers"][0]["capacity"], 1)
            executors = request_json(
                f"{base_url}/executors",
                headers={"authorization": "Bearer secret"},
            )
            self.assertIn("executor_registry", executors)
            access = request_json(
                f"{base_url}/access/policy",
                headers={"authorization": "Bearer secret", "x-remote-user": "alice"},
            )
            self.assertEqual(access["current_principal"]["id"], "alice")
            self.assertIn("owner", {role["id"] for role in access["roles"]})
            self.assertIn("runs:*", access["scopes"])
            projects = request_json(
                f"{base_url}/access/projects",
                headers={"authorization": "Bearer secret"},
            )
            self.assertIn("default", {project["project_id"] for project in projects["projects"]})
            project = request_json(
                f"{base_url}/access/projects",
                method="POST",
                payload={"project_id": "team1", "display_name": "Team 1"},
                headers={"authorization": "Bearer secret"},
            )
            self.assertEqual(project["project_id"], "team1")
            token = request_json(
                f"{base_url}/access/tokens",
                method="POST",
                payload={"name": "smoke", "project_id": "team1", "scopes": ["runs:read"]},
                headers={
                    "authorization": "Bearer secret",
                    "x-remote-user": "alice@example.com",
                },
            )
            self.assertIn("token", token)
            self.assertEqual(token["principal_id"], "alice@example.com")
            self.assertNotIn("token_hash", token)
            token_capabilities = request_json(
                f"{base_url}/capabilities",
                headers={"authorization": f"Bearer {token['token']}"},
            )
            self.assertIn("fake", token_capabilities["adapters"])
            with self.assertRaises(urllib.error.HTTPError) as scoped_ctx:
                request_json(
                    f"{base_url}/cleanup",
                    method="POST",
                    payload={},
                    headers={"authorization": f"Bearer {token['token']}"},
                )
            self.assertEqual(scoped_ctx.exception.code, HTTPStatus.FORBIDDEN)
            tokens = request_json(
                f"{base_url}/access/tokens",
                headers={"authorization": "Bearer secret"},
            )
            self.assertIn(token["token_id"], {item["token_id"] for item in tokens["tokens"]})
            revoked = request_json(
                f"{base_url}/access/tokens/{token['token_id']}/revoke",
                method="POST",
                payload={},
                headers={"authorization": "Bearer secret"},
            )
            self.assertEqual(revoked["status"], "revoked")
            with self.assertRaises(urllib.error.HTTPError) as revoked_ctx:
                request_json(
                    f"{base_url}/capabilities",
                    headers={"authorization": f"Bearer {token['token']}"},
                )
            self.assertEqual(revoked_ctx.exception.code, HTTPStatus.UNAUTHORIZED)
            cost = request_json(
                f"{base_url}/cost/status",
                headers={"authorization": "Bearer secret"},
            )
            self.assertIn("monthly_estimated_cost_usd", cost)

            with self.assertRaises(urllib.error.HTTPError) as cleanup_ctx:
                request_json(f"{base_url}/cleanup", method="POST", payload={})
            self.assertEqual(cleanup_ctx.exception.code, HTTPStatus.UNAUTHORIZED)
            cleanup = request_json(
                f"{base_url}/cleanup",
                method="POST",
                payload={},
                headers={"authorization": "Bearer secret"},
            )
            self.assertIn("cleanup", cleanup)

    def test_v2_task_workflow_artifact_retry_and_replay_api(self) -> None:
        with running_runtime(token="secret") as base_url:
            headers = {"authorization": "Bearer secret"}
            created = request_json(
                f"{base_url}/v2/tasks",
                method="POST",
                payload={
                    "goal": "Coordinate a V2 HTTP workflow",
                    "mode": "workflow",
                    "adapter": "codex",
                    "channel": "feishu",
                },
                headers=headers,
            )
            task_id = created["task_id"]
            deadline = time.time() + 3
            current = created
            while time.time() < deadline:
                current = request_json(f"{base_url}/v2/tasks/{task_id}", headers=headers)
                if current["status"] == "completed":
                    break
                time.sleep(0.05)

            self.assertEqual(current["status"], "completed")
            workflow = request_json(
                f"{base_url}/v2/tasks/{task_id}/workflow",
                headers=headers,
            )
            artifacts = request_json(
                f"{base_url}/v2/tasks/{task_id}/artifacts",
                headers=headers,
            )
            artifact = request_json(
                f"{base_url}/v2/tasks/{task_id}/artifacts/"
                f"{artifacts['artifacts'][0]['artifact_id']}",
                headers=headers,
            )
            audit = request_json(
                f"{base_url}/v2/tasks/{task_id}/audit.json", headers=headers
            )
            executed = request_json(
                f"{base_url}/v2/internal/tasks/{task_id}/execute",
                method="POST",
                payload={},
                headers=headers,
            )
            evaluations = request_json(
                f"{base_url}/v2/tasks/{task_id}/evaluations",
                headers=headers,
            )
            replay = request_json(
                f"{base_url}/v2/tasks/{task_id}/replay",
                method="POST",
                payload={},
                headers=headers,
            )
            replays = request_json(
                f"{base_url}/v2/tasks/{task_id}/replays",
                headers=headers,
            )
            retried = request_json(
                f"{base_url}/v2/tasks/{task_id}/retry",
                method="POST",
                payload={},
                headers=headers,
            )
            unit = request_json(
                f"{base_url}/v2/admin/execution-units",
                method="POST",
                payload={"unit_id": "docker-http", "kind": "docker", "adapters": ["fake"]},
                headers=headers,
            )
            tenant = request_json(
                f"{base_url}/v2/admin/tenants",
                method="POST",
                payload={"tenant_id": "tenant_http", "name": "HTTP Tenant"},
                headers=headers,
            )
            project = request_json(
                f"{base_url}/v2/admin/projects",
                method="POST",
                payload={"project_id": "project_http", "name": "HTTP Project"},
                headers=headers,
            )
            project_member = request_json(
                f"{base_url}/v2/admin/projects/project_http/members",
                method="POST",
                payload={"user_id": "viewer@example.com", "role": "viewer"},
                headers=headers,
            )
            projects = request_json(f"{base_url}/v2/admin/projects", headers=headers)
            project_members = request_json(
                f"{base_url}/v2/admin/projects/project_http/members", headers=headers
            )
            user = request_json(
                f"{base_url}/v2/admin/tenants/tenant_http/users",
                method="POST",
                payload={"email": "ops@example.com", "roles": ["operator"]},
                headers=headers,
            )
            policy = request_json(
                f"{base_url}/v2/admin/tenants/tenant_http/rbac",
                method="POST",
                payload={"role": "operator", "permissions": ["tasks:*"]},
                headers=headers,
            )
            channel = request_json(
                f"{base_url}/v2/admin/channels/feishu/config",
                method="POST",
                payload={"callback_token": "secret", "webhook_url": "http://127.0.0.1:1"},
                headers=headers,
            )
            webhook = request_json(
                f"{base_url}/v2/channels/feishu/webhook",
                method="POST",
                payload={
                    "event": {
                        "message": {
                            "message_id": "http_msg_1",
                            "content": '{"text":"Start from Feishu"}',
                        }
                    }
                },
                headers={"x-agentflow-channel-token": "secret"},
            )
            sent = request_json(
                f"{base_url}/v2/admin/channels/feishu/send",
                method="POST",
                payload={"task_id": task_id, "message": "hello"},
                headers=headers,
            )
            messages = request_json(
                f"{base_url}/v2/admin/channel-messages",
                headers=headers,
            )
            tenants = request_json(f"{base_url}/v2/admin/tenants", headers=headers)
            users = request_json(
                f"{base_url}/v2/admin/tenants/tenant_http/users",
                headers=headers,
            )
            policies = request_json(
                f"{base_url}/v2/admin/tenants/tenant_http/rbac",
                headers=headers,
            )
            ha = request_json(f"{base_url}/v2/admin/ha", headers=headers)
            engines = request_json(
                f"{base_url}/v2/admin/workflow-engines",
                headers=headers,
            )
            discovery = request_json(
                f"{base_url}/v2/admin/execution-units/discover",
                method="POST",
                payload={},
                headers=headers,
            )

            self.assertEqual(workflow["run"]["engine"], "local-sqlite-dag")
            self.assertEqual(len(workflow["steps"]), 3)
            self.assertTrue(artifacts["artifacts"])
            self.assertEqual(artifact["task_id"], task_id)
            self.assertEqual(audit["task"]["task_id"], task_id)
            self.assertEqual(executed["status"], "completed")
            self.assertTrue(evaluations["evaluations"])
            self.assertEqual(replay["status"], "created")
            self.assertTrue(replays["replays"])
            self.assertIn(retried["status"], {"queued", "running", "completed"})
            self.assertEqual(unit["unit_id"], "docker-http")
            self.assertEqual(tenant["tenant_id"], "tenant_http")
            self.assertEqual(project["project_id"], "project_http")
            self.assertEqual(project_member["role"], "viewer")
            self.assertIn("project_http", {item["project_id"] for item in projects["projects"]})
            self.assertEqual(project_members["members"][-1]["user_id"], "viewer@example.com")
            self.assertEqual(user["roles"], ["operator"])
            self.assertEqual(policy["permissions"], ["tasks:*"])
            self.assertEqual(channel["config"]["callback_token"], "<configured>")
            self.assertTrue(webhook["accepted"])
            self.assertIn(sent["status"], {"queued", "failed"})
            self.assertTrue(messages["messages"])
            self.assertTrue(tenants["tenants"])
            self.assertEqual(users["users"][0]["email"], "ops@example.com")
            self.assertEqual(policies["policies"][0]["role"], "operator")
            self.assertIn("database", ha)
            self.assertIn("engines", engines)
            self.assertIn("units", discovery)

    def test_v2_task_creation_without_auth_uses_api_principal(self) -> None:
        with running_runtime() as base_url:
            created = request_json(
                f"{base_url}/v2/tasks",
                method="POST",
                payload={"goal": "Open the chat-first task page", "adapter": "fake"},
            )
            self.assertEqual(created["created_by"], "api-token")

    def test_v2_webshell_events_stream_as_sse_and_resume(self) -> None:
        with running_runtime(token="secret") as base_url:
            headers = {"authorization": "Bearer secret"}
            created = request_json(
                f"{base_url}/v2/tasks",
                method="POST",
                payload={"goal": "Stream V2 agent chat", "adapter": "fake"},
                headers=headers,
            )
            stream_url = (
                f"{base_url}/v2/tasks/{created['task_id']}/webshell/events"
            )
            streamed = read_sse(stream_url, headers=headers)

            self.assertTrue(streamed)
            self.assertEqual({event["event"] for event in streamed}, {"message"})
            event_types = {
                event["data"]["_meta"]["runtimeEventType"] for event in streamed
            }
            self.assertIn("agent.message", event_types)
            self.assertIn("task.completed", event_types)

            resumed = read_sse(
                stream_url,
                headers={**headers, "Last-Event-ID": "2"},
            )
            self.assertTrue(resumed)
            self.assertTrue(all(int(event["data"]["id"]) > 2 for event in resumed))

            with self.assertRaises(urllib.error.HTTPError) as missing:
                read_sse(
                    f"{base_url}/v2/tasks/missing/webshell/events",
                    headers=headers,
                )
            self.assertEqual(missing.exception.code, HTTPStatus.NOT_FOUND)

    def test_console_login_session_cookie_authorizes_api(self) -> None:
        with running_runtime(
            token="secret",
            login_user="cloudagents",
            login_password="password",
            bootstrap_email="owner@example.com",
        ) as base_url:
            session = request_json(f"{base_url}/auth/session")
            self.assertFalse(session["authenticated"])
            html = request_text(f"{base_url}/")
            self.assertIn("aflow Console", html)
            with self.assertRaises(urllib.error.HTTPError) as unauthorized:
                request_json(f"{base_url}/capabilities")
            self.assertEqual(unauthorized.exception.code, HTTPStatus.UNAUTHORIZED)
            with self.assertRaises(urllib.error.HTTPError) as bad_login:
                request_json(
                    f"{base_url}/auth/login",
                    method="POST",
                    payload={"email": "owner@example.com", "password": "wrong"},
                )
            self.assertEqual(bad_login.exception.code, HTTPStatus.UNAUTHORIZED)

            login_response = request_raw(
                f"{base_url}/auth/login",
                method="POST",
                payload={"email": "owner@example.com", "password": "password"},
            )
            cookie = login_response.headers["set-cookie"]
            self.assertIn("HttpOnly", cookie)
            self.assertNotIn("owner@example.com", cookie)
            capabilities = request_json(
                f"{base_url}/capabilities",
                headers={"cookie": cookie},
            )
            self.assertIn("fake", capabilities["adapters"])
            access = request_json(
                f"{base_url}/access/policy",
                headers={"cookie": cookie},
            )
            self.assertEqual(access["current_principal"]["id"], "owner@example.com")
            access_with_legacy_bearer = request_json(
                f"{base_url}/access/policy",
                headers={
                    "authorization": "Bearer secret",
                    "cookie": cookie,
                    "x-remote-user": "proxy-user",
                },
            )
            self.assertEqual(
                access_with_legacy_bearer["current_principal"]["id"],
                "owner@example.com",
            )
            legacy_login = request_raw(
                f"{base_url}/auth/login",
                method="POST",
                payload={"username": "cloudagents", "password": "password"},
            )
            self.assertIn("HttpOnly", legacy_login.headers["set-cookie"])
            redirect = request_no_redirect(
                f"{base_url}/access",
                headers={
                    "accept": "text/html",
                    "x-forwarded-prefix": "/cloud-agents",
                },
            )
            self.assertEqual(redirect.status, HTTPStatus.FOUND)
            self.assertEqual(redirect.headers["location"], "/cloud-agents/#/access")
            created = request_json(
                f"{base_url}/access/tokens",
                method="POST",
                payload={"name": "console", "scopes": ["runs:read"]},
                headers={"cookie": cookie},
            )
            self.assertEqual(created["principal_id"], "owner@example.com")
            user = request_json(
                f"{base_url}/auth/users",
                method="POST",
                payload={
                    "email": "operator@example.com",
                    "display_name": "Operator",
                    "password": "operator-password",
                    "roles": ["operator"],
                },
                headers={"cookie": cookie},
            )
            self.assertEqual(user["email"], "operator@example.com")
            self.assertNotIn("password_hash", user)
            users = request_json(f"{base_url}/auth/users", headers={"cookie": cookie})
            self.assertEqual(
                [item["email"] for item in users["users"]],
                ["operator@example.com", "owner@example.com"],
            )
            with self.assertRaises(urllib.error.HTTPError) as duplicate_user:
                request_json(
                    f"{base_url}/auth/users",
                    method="POST",
                    payload={
                        "email": "operator@example.com",
                        "password": "operator-password",
                    },
                    headers={"cookie": cookie},
                )
            self.assertEqual(duplicate_user.exception.code, HTTPStatus.BAD_REQUEST)
            member = request_json(
                f"{base_url}/auth/users",
                method="POST",
                payload={
                    "email": "member@example.com",
                    "display_name": "Member",
                    "password": "member-password",
                },
                headers={"cookie": cookie},
            )
            self.assertEqual(member["roles"], ["member"])
            role_update = request_json(
                f"{base_url}/auth/users/member@example.com/roles",
                method="POST",
                payload={"roles": ["auditor"]},
                headers={"cookie": cookie},
            )
            self.assertEqual(role_update["roles"], ["auditor"])
            password_update = request_json(
                f"{base_url}/auth/users/member@example.com/password",
                method="POST",
                payload={"password": "member-password-2"},
                headers={"cookie": cookie},
            )
            self.assertEqual(password_update["email"], "member@example.com")
            with self.assertRaises(urllib.error.HTTPError) as old_member_login:
                request_json(
                    f"{base_url}/auth/login",
                    method="POST",
                    payload={
                        "email": "member@example.com",
                        "password": "member-password",
                    },
                )
            self.assertEqual(old_member_login.exception.code, HTTPStatus.UNAUTHORIZED)
            member_login = request_raw(
                f"{base_url}/auth/login",
                method="POST",
                payload={
                    "email": "member@example.com",
                    "password": "member-password-2",
                },
            )
            self.assertIn("HttpOnly", member_login.headers["set-cookie"])
            status_update = request_json(
                f"{base_url}/auth/users/member@example.com/status",
                method="POST",
                payload={"status": "disabled"},
                headers={"cookie": cookie},
            )
            self.assertEqual(status_update["status"], "disabled")
            with self.assertRaises(urllib.error.HTTPError) as disabled_member_login:
                request_json(
                    f"{base_url}/auth/login",
                    method="POST",
                    payload={
                        "email": "member@example.com",
                        "password": "member-password-2",
                    },
                )
            self.assertEqual(disabled_member_login.exception.code, HTTPStatus.UNAUTHORIZED)
            with self.assertRaises(urllib.error.HTTPError) as disable_self:
                request_json(
                    f"{base_url}/auth/users/owner@example.com/status",
                    method="POST",
                    payload={"status": "disabled"},
                    headers={"cookie": cookie},
                )
            self.assertEqual(disable_self.exception.code, HTTPStatus.BAD_REQUEST)
            operator_login = request_raw(
                f"{base_url}/auth/login",
                method="POST",
                payload={
                    "email": "operator@example.com",
                    "password": "operator-password",
                },
            )
            self.assertIn("HttpOnly", operator_login.headers["set-cookie"])
            operator_cookie = operator_login.headers["set-cookie"]
            operator_run = request_json(
                f"{base_url}/runs",
                method="POST",
                payload={"prompt": "operator can create runs", "adapter": "fake"},
                headers={"cookie": operator_cookie},
            )
            self.assertTrue(operator_run["run_id"].startswith("run_"))
            operator_events = request_json(
                f"{base_url}/runs/{operator_run['run_id']}/events.json",
                headers={"cookie": operator_cookie},
            )
            self.assertIn("events", operator_events)
            operator_session_events = request_json(
                f"{base_url}/session/{operator_run['run_id']}/events.json",
                headers={"cookie": operator_cookie},
            )
            self.assertIn("events", operator_session_events)
            operator_artifacts = request_json(
                f"{base_url}/runs/{operator_run['run_id']}/artifacts",
                headers={"cookie": operator_cookie},
            )
            self.assertIn("artifacts", operator_artifacts)
            with self.assertRaises(urllib.error.HTTPError) as operator_user_create:
                request_json(
                    f"{base_url}/auth/users",
                    method="POST",
                    payload={
                        "email": "blocked@example.com",
                        "password": "operator-password",
                    },
                    headers={"cookie": operator_cookie},
                )
            self.assertEqual(operator_user_create.exception.code, HTTPStatus.FORBIDDEN)
            with self.assertRaises(urllib.error.HTTPError) as operator_token_create:
                request_json(
                    f"{base_url}/access/tokens",
                    method="POST",
                    payload={"name": "blocked"},
                    headers={"cookie": operator_cookie},
                )
            self.assertEqual(operator_token_create.exception.code, HTTPStatus.FORBIDDEN)

            logout_response = request_raw(
                f"{base_url}/auth/logout",
                method="POST",
                payload={},
                headers={"cookie": cookie},
            )
            self.assertIn("Max-Age=0", logout_response.headers["set-cookie"])
            with self.assertRaises(urllib.error.HTTPError) as logged_out:
                request_json(f"{base_url}/capabilities", headers={"cookie": cookie})
            self.assertEqual(logged_out.exception.code, HTTPStatus.UNAUTHORIZED)

    def test_remote_worker_http_registry_claims_and_reports_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with running_runtime(
                artifact_root=Path(tmp),
                token="secret",
                worker_capacity=0,
            ) as base_url:
                headers = {"authorization": "Bearer secret"}
                run = request_json(
                    f"{base_url}/runs",
                    method="POST",
                    payload={"prompt": "remote http", "adapter": "fake"},
                    headers=headers,
                )
                token = request_json(
                    f"{base_url}/access/tokens",
                    method="POST",
                    payload={"name": "worker", "scopes": ["workers:*"]},
                    headers=headers,
                )
                worker_headers = {"authorization": f"Bearer {token['token']}"}
                with self.assertRaises(urllib.error.HTTPError) as access_ctx:
                    request_json(f"{base_url}/access/tokens", headers=worker_headers)
                self.assertEqual(access_ctx.exception.code, HTTPStatus.FORBIDDEN)
                heartbeat = request_json(
                    f"{base_url}/workers/vps-a/heartbeat",
                    method="POST",
                    payload={
                        "capacity": 1,
                        "lease_ttl_seconds": 30,
                        "endpoint": "https://worker-a.example",
                        "capabilities": {"adapters": ["fake"], "container": True},
                    },
                    headers=worker_headers,
                )
                self.assertEqual(heartbeat["worker"]["metadata"]["kind"], "remote")
                worker = request_json(
                    f"{base_url}/workers/vps-a",
                    headers=worker_headers,
                )
                self.assertEqual(
                    worker["worker"]["metadata"]["endpoint"],
                    "https://worker-a.example",
                )

                claim = request_json(
                    f"{base_url}/workers/vps-a/claim",
                    method="POST",
                    payload={"capacity": 1, "lease_ttl_seconds": 30},
                    headers=worker_headers,
                )
                self.assertEqual(claim["run"]["run_id"], run["run_id"])
                self.assertEqual(claim["job"]["worker_id"], "vps-a")
                request_json(
                    f"{base_url}/workers/vps-a/runs/{run['run_id']}/events",
                    method="POST",
                    payload={"type": "run.started", "data": {"adapter": "remote"}},
                    headers=worker_headers,
                )
                request_json(
                    f"{base_url}/workers/vps-a/runs/{run['run_id']}/artifacts",
                    method="POST",
                    payload={"name": "remote_result.json", "json": {"ok": True}},
                    headers=worker_headers,
                )
                request_json(
                    f"{base_url}/workers/vps-a/runs/{run['run_id']}/artifacts",
                    method="POST",
                    payload={
                        "name": "remote.log",
                        "content": "hello ",
                        "mode": "append",
                        "chunk_index": 1,
                    },
                    headers=worker_headers,
                )
                request_json(
                    f"{base_url}/workers/vps-a/runs/{run['run_id']}/artifacts",
                    method="POST",
                    payload={
                        "name": "remote.log",
                        "content": "worker",
                        "mode": "append",
                        "chunk_index": 2,
                        "final": True,
                    },
                    headers=worker_headers,
                )
                request_json(
                    f"{base_url}/workers/vps-a/runs/{run['run_id']}/events",
                    method="POST",
                    payload={"type": "run.completed", "data": {"summary": "done"}},
                    headers=worker_headers,
                )
                completed = request_json(f"{base_url}/runs/{run['run_id']}", headers=headers)
                self.assertEqual(completed["status"], "completed")
                artifacts = request_json(
                    f"{base_url}/runs/{run['run_id']}/artifacts",
                    headers=headers,
                )
                self.assertIn(
                    "remote_result.json",
                    {artifact["name"] for artifact in artifacts["artifacts"]},
                )
                self.assertIn(
                    "remote.log",
                    {artifact["name"] for artifact in artifacts["artifacts"]},
                )
                self.assertEqual(
                    (Path(tmp) / run["run_id"] / "remote.log").read_text(),
                    "hello worker",
                )

    def test_worker_registration_drain_resume_and_retry_api(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with running_runtime(
                artifact_root=Path(tmp),
                token="secret",
                worker_capacity=0,
            ) as base_url:
                headers = {"authorization": "Bearer secret"}
                registration = request_json(
                    f"{base_url}/workers/registrations",
                    method="POST",
                    payload={
                        "worker_id": "hk-2c2g-a",
                        "control_url": "https://example.com/cloud-agents-worker",
                        "capacity": 1,
                        "labels": {"region": "hk"},
                        "resources": {"cpus": 2, "memory_gb": 2},
                    },
                    headers=headers,
                )
                self.assertEqual(registration["worker_id"], "hk-2c2g-a")
                self.assertIn("RUN_WORKER_TOKEN=", registration["deploy_command"])
                self.assertIn("scripts/deploy_worker_vps.sh", registration["deploy_command"])

                token = registration["token"]["token"]
                worker_headers = {"authorization": f"Bearer {token}"}
                run = request_json(
                    f"{base_url}/runs",
                    method="POST",
                    payload={"prompt": "remote retry", "adapter": "fake"},
                    headers=headers,
                )
                request_json(
                    f"{base_url}/workers/hk-2c2g-a/heartbeat",
                    method="POST",
                    payload={
                        "capacity": 1,
                        "lease_ttl_seconds": 30,
                        "metadata": {"capabilities": {"adapters": ["fake"]}},
                    },
                    headers=worker_headers,
                )
                drained = request_json(
                    f"{base_url}/workers/hk-2c2g-a/drain",
                    method="POST",
                    payload={"reason": "maintenance"},
                    headers=headers,
                )
                self.assertEqual(drained["worker"]["status"], "draining")
                claim_while_draining = request_json(
                    f"{base_url}/workers/hk-2c2g-a/claim",
                    method="POST",
                    payload={"capacity": 1, "lease_ttl_seconds": 30},
                    headers=worker_headers,
                )
                self.assertIsNone(claim_while_draining["run"])

                resumed = request_json(
                    f"{base_url}/workers/hk-2c2g-a/resume",
                    method="POST",
                    payload={},
                    headers=headers,
                )
                self.assertEqual(resumed["worker"]["status"], "active")
                claim = request_json(
                    f"{base_url}/workers/hk-2c2g-a/claim",
                    method="POST",
                    payload={"capacity": 1, "lease_ttl_seconds": 30},
                    headers=worker_headers,
                )
                self.assertEqual(claim["run"]["run_id"], run["run_id"])
                retried = request_json(
                    f"{base_url}/workers/hk-2c2g-a/retry",
                    method="POST",
                    payload={"reason": "operator retry"},
                    headers=headers,
                )
                self.assertEqual(retried["requeued_run_ids"], [run["run_id"]])
                control = request_json(
                    f"{base_url}/workers/hk-2c2g-a/control",
                    headers=worker_headers,
                )
                self.assertEqual(control["desired_state"], "active")

    def test_fake_run_streams_sse_and_writes_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with running_runtime(artifact_root=Path(tmp)) as base_url:
                html = request_text(f"{base_url}/")
                self.assertIn("aflow Console", html)
                self.assertIn('id="root"', html)
                self.assertIn("./assets/", html)
                asset_match = re.search(r'src="\.(/assets/[^"]+)"', html)
                self.assertIsNotNone(asset_match)
                asset_body = request_text(f"{base_url}{asset_match.group(1)}")
                self.assertIn("aflow", asset_body)
                run = request_json(
                    f"{base_url}/runs",
                    method="POST",
                    payload={"prompt": "hello integration runtime", "adapter": "fake"},
                )
                events = read_sse(f"{base_url}/runs/{run['run_id']}/events")
                event_names = [event["event"] for event in events]
                self.assertIn("run.created", event_names)
                self.assertIn("resources.resolved", event_names)
                self.assertIn("cost.quoted", event_names)
                self.assertIn("run.completed", event_names)
                run_dir = Path(tmp) / run["run_id"]
                self.assertTrue((run_dir / "events.jsonl").exists())
                self.assertTrue((run_dir / "final_1.json").exists())
                self.assertTrue((run_dir / "workspace.json").exists())
                self.assertTrue((run_dir / "resources.json").exists())
                self.assertTrue((run_dir / "cost.json").exists())
                events_json = request_json(f"{base_url}/runs/{run['run_id']}/events.json")
                self.assertIn("events", events_json)
                artifacts = request_json(f"{base_url}/runs/{run['run_id']}/artifacts")
                artifact_names = {artifact["name"] for artifact in artifacts["artifacts"]}
                self.assertIn("events.jsonl", artifact_names)
                self.assertIn("diagnostics.json", artifact_names)
                self.assertIn("workspace.json", artifact_names)
                self.assertIn("resources.json", artifact_names)
                self.assertIn("cost.json", artifact_names)
                final_artifact = request_text(
                    f"{base_url}/runs/{run['run_id']}/artifacts/final_1.json"
                )
                self.assertIn("hello integration runtime", final_artifact)
                audit = request_json(f"{base_url}/runs/{run['run_id']}/audit.json")
                self.assertEqual(audit["run"]["run_id"], run["run_id"])
                self.assertIn("events", audit)
                self.assertIn("raw_events", audit)
                self.assertIn("artifacts", audit)
                with self.assertRaises(urllib.error.HTTPError) as bad_artifact:
                    request_text(
                        f"{base_url}/runs/{run['run_id']}/artifacts/%2E%2E%2Fruntime.db"
                    )
                self.assertEqual(bad_artifact.exception.code, HTTPStatus.BAD_REQUEST)

    def test_task_workspace_bff_wraps_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with running_runtime(artifact_root=Path(tmp)) as base_url:
                task = request_json(
                    f"{base_url}/tasks",
                    method="POST",
                    payload={"goal": "prepare task workspace smoke", "adapter": "fake"},
                )
                self.assertTrue(task["task_id"].startswith("run_"))
                self.assertEqual(task["kind"], "run")
                self.assertEqual(task["goal"], "prepare task workspace smoke")
                wait_for_run_status(base_url, task["task_id"], "completed")
                tasks = request_json(f"{base_url}/tasks")
                self.assertIn(task["task_id"], {item["task_id"] for item in tasks["tasks"]})
                detail = request_json(f"{base_url}/tasks/{task['task_id']}")
                self.assertEqual(detail["source"]["run_id"], task["task_id"])
                events = request_json(f"{base_url}/tasks/{task['task_id']}/events.json")
                self.assertIn("task.accepted", {event["type"] for event in events["events"]})
                self.assertIn("task.completed", {event["type"] for event in events["events"]})
                result = request_json(f"{base_url}/tasks/{task['task_id']}/result")
                self.assertEqual(result["task_id"], task["task_id"])
                self.assertTrue(result["artifacts"])
                artifacts = request_json(f"{base_url}/tasks/{task['task_id']}/artifacts")
                self.assertIn(
                    "final_1.json",
                    {artifact["name"] for artifact in artifacts["artifacts"]},
                )

    def test_task_workspace_bff_accepts_cancel_and_messages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with running_runtime(artifact_root=Path(tmp), worker_capacity=0) as base_url:
                task = request_json(
                    f"{base_url}/tasks",
                    method="POST",
                    payload={"goal": "queued task", "adapter": "fake"},
                )
                accepted = request_json(
                    f"{base_url}/tasks/{task['task_id']}/messages",
                    method="POST",
                    payload={"message": "extra context"},
                )
                self.assertTrue(accepted["accepted"])
                cancelled = request_json(
                    f"{base_url}/tasks/{task['task_id']}/cancel",
                    method="POST",
                    payload={"reason": "test"},
                )
                self.assertEqual(cancelled["status"], "cancelled")

    def test_task_workspace_filters_by_session_principal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with running_runtime(
                artifact_root=Path(tmp),
                token="secret",
                login_user="cloudagents",
                login_password="password",
                bootstrap_email="owner@example.com",
                worker_capacity=0,
            ) as base_url:
                owner_cookie = request_raw(
                    f"{base_url}/auth/login",
                    method="POST",
                    payload={"email": "owner@example.com", "password": "password"},
                ).headers["set-cookie"]
                for email in ("alice@example.com", "bob@example.com"):
                    created = request_json(
                        f"{base_url}/auth/users",
                        method="POST",
                        headers={"cookie": owner_cookie},
                        payload={
                            "email": email,
                            "display_name": email.split("@", 1)[0].title(),
                            "password": "password",
                            "roles": ["member"],
                            "email_verified": True,
                        },
                    )
                    self.assertEqual(created["email"], email)

                alice_cookie = request_raw(
                    f"{base_url}/auth/login",
                    method="POST",
                    payload={"email": "alice@example.com", "password": "password"},
                ).headers["set-cookie"]
                bob_cookie = request_raw(
                    f"{base_url}/auth/login",
                    method="POST",
                    payload={"email": "bob@example.com", "password": "password"},
                ).headers["set-cookie"]

                alice_task = request_json(
                    f"{base_url}/tasks",
                    method="POST",
                    headers={"cookie": alice_cookie},
                    payload={"goal": "alice private workspace task", "adapter": "fake"},
                )
                bob_task = request_json(
                    f"{base_url}/tasks",
                    method="POST",
                    headers={"cookie": bob_cookie},
                    payload={"goal": "bob private workspace task", "adapter": "fake"},
                )
                self.assertEqual(alice_task["access"]["created_by"], "alice@example.com")
                self.assertEqual(bob_task["access"]["created_by"], "bob@example.com")

                alice_tasks = request_json(
                    f"{base_url}/tasks",
                    headers={"cookie": alice_cookie},
                )["tasks"]
                self.assertEqual({task["task_id"] for task in alice_tasks}, {alice_task["task_id"]})
                with self.assertRaises(urllib.error.HTTPError) as hidden_runs:
                    request_json(f"{base_url}/runs", headers={"cookie": alice_cookie})
                self.assertEqual(hidden_runs.exception.code, HTTPStatus.FORBIDDEN)
                with self.assertRaises(urllib.error.HTTPError) as hidden_detail:
                    request_json(
                        f"{base_url}/tasks/{bob_task['task_id']}",
                        headers={"cookie": alice_cookie},
                    )
                self.assertEqual(hidden_detail.exception.code, HTTPStatus.NOT_FOUND)
                with self.assertRaises(urllib.error.HTTPError) as hidden_message:
                    request_json(
                        f"{base_url}/tasks/{bob_task['task_id']}/messages",
                        method="POST",
                        headers={"cookie": alice_cookie},
                        payload={"message": "peek"},
                    )
                self.assertEqual(hidden_message.exception.code, HTTPStatus.NOT_FOUND)

                owner_tasks = request_json(
                    f"{base_url}/tasks",
                    headers={"cookie": owner_cookie},
                )["tasks"]
                self.assertEqual(
                    {alice_task["task_id"], bob_task["task_id"]},
                    {task["task_id"] for task in owner_tasks},
                )

    def test_task_workspace_bff_wraps_missions_and_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with running_runtime(artifact_root=Path(tmp), worker_capacity=0) as base_url:
                with self.assertRaises(urllib.error.HTTPError) as missing_goal:
                    request_json(f"{base_url}/tasks", method="POST", payload={})
                self.assertEqual(missing_goal.exception.code, HTTPStatus.BAD_REQUEST)

                mission_task = request_json(
                    f"{base_url}/tasks",
                    method="POST",
                    payload={
                        "goal": "plan a mission task",
                        "mode": "mission",
                        "strategy": "sequential",
                        "adapter": "fake",
                    },
                )
                self.assertTrue(mission_task["task_id"].startswith("mission_"))
                self.assertEqual(mission_task["kind"], "mission")
                self.assertIn(mission_task["status"], {"queued", "running"})
                mission_detail = request_json(f"{base_url}/tasks/{mission_task['task_id']}")
                self.assertEqual(mission_detail["source"]["mission_id"], mission_task["task_id"])
                mission_events = request_json(
                    f"{base_url}/tasks/{mission_task['task_id']}/events.json"
                )
                self.assertIn("events", mission_events)
                mission_artifacts = request_json(
                    f"{base_url}/tasks/{mission_task['task_id']}/artifacts"
                )
                self.assertIn("artifacts", mission_artifacts)
                mission_result = request_json(
                    f"{base_url}/tasks/{mission_task['task_id']}/result"
                )
                self.assertEqual(mission_result["task_id"], mission_task["task_id"])
                with self.assertRaises(urllib.error.HTTPError) as mission_message:
                    request_json(
                        f"{base_url}/tasks/{mission_task['task_id']}/messages",
                        method="POST",
                        payload={"message": "continue"},
                    )
                self.assertEqual(mission_message.exception.code, HTTPStatus.BAD_REQUEST)
                cancelled = request_json(
                    f"{base_url}/tasks/{mission_task['task_id']}/cancel",
                    method="POST",
                    payload={"reason": "test"},
                )
                self.assertEqual(cancelled["status"], "cancelled")

                for suffix in ("", "/events.json", "/artifacts", "/result"):
                    with self.assertRaises(urllib.error.HTTPError) as missing_task:
                        request_json(f"{base_url}/tasks/run_missing{suffix}")
                    self.assertEqual(missing_task.exception.code, HTTPStatus.NOT_FOUND)
                with self.assertRaises(urllib.error.HTTPError) as missing_cancel:
                    request_json(
                        f"{base_url}/tasks/run_missing/cancel",
                        method="POST",
                        payload={},
                    )
                self.assertEqual(missing_cancel.exception.code, HTTPStatus.NOT_FOUND)
                with self.assertRaises(urllib.error.HTTPError) as missing_message:
                    request_json(
                        f"{base_url}/tasks/run_missing/messages",
                        method="POST",
                        payload={"message": "hello"},
                    )
                self.assertEqual(missing_message.exception.code, HTTPStatus.NOT_FOUND)
                with self.assertRaises(urllib.error.HTTPError) as empty_message:
                    request_json(
                        f"{base_url}/tasks/{mission_task['task_id']}/messages",
                        method="POST",
                        payload={},
                    )
                self.assertEqual(empty_message.exception.code, HTTPStatus.BAD_REQUEST)

    def test_session_bff_projects_run_events_to_daemon_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with running_runtime(artifact_root=Path(tmp)) as base_url:
                session = request_json(
                    f"{base_url}/session",
                    method="POST",
                    payload={"adapter": "fake"},
                )
                session_id = session["session"]["id"]
                self.assertEqual(session_id, session["run"]["run_id"])
                wait_for_run_status(base_url, session_id, "running")

                accepted = request_json(
                    f"{base_url}/session/{session_id}/prompt",
                    method="POST",
                    payload={"prompt": "render daemon transcript"},
                )
                self.assertTrue(accepted["accepted"])

                events = read_sse(f"{base_url}/session/{session_id}/events")
                event_types = [event["event"] for event in events]
                self.assertIn("session_update", event_types)
                self.assertIn("turn_complete", event_types)
                first = events[0]["data"]
                self.assertEqual(first["v"], 1)
                self.assertEqual(first["_meta"]["runtimeRunId"], session_id)
                self.assertIn("runtimeSequence", first["_meta"])
                self.assertTrue(
                    any(
                        event["data"]
                        .get("data", {})
                        .get("update", {})
                        .get("sessionUpdate")
                        == "agent_message_chunk"
                        for event in events
                    )
                )

                replayed = read_sse(
                    f"{base_url}/session/{session_id}/events",
                    headers={"Last-Event-ID": "2"},
                )
                self.assertTrue(all(event["data"]["id"] > 2 for event in replayed))

                gap = read_sse(
                    f"{base_url}/session/{session_id}/events",
                    headers={"Last-Event-ID": "999"},
                )
                self.assertEqual(gap[0]["event"], "stream_error")

                projected = request_json(f"{base_url}/session/{session_id}/events.json")
                self.assertIn("events", projected)
                ui_cache = Path(tmp) / session_id / "ui_daemon_events.jsonl"
                self.assertTrue(ui_cache.exists())
                self.assertIn("turn_complete", ui_cache.read_text(encoding="utf-8"))
                audit = request_json(f"{base_url}/runs/{session_id}/audit.json")
                self.assertIn("ui_daemon_events", audit)
                self.assertTrue(
                    any(event["type"] == "turn_complete" for event in audit["ui_daemon_events"])
                )

    def test_profiles_and_missions_http_api(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with running_runtime(artifact_root=Path(tmp), worker_capacity=2) as base_url:
                profiles = request_json(f"{base_url}/profiles")
                self.assertIn("planner", {profile["id"] for profile in profiles["profiles"]})
                custom = request_json(
                    f"{base_url}/profiles",
                    method="POST",
                    payload={
                        "id": "doc-reviewer",
                        "display_name": "Doc Reviewer",
                        "runtime": {"preferred_adapter": "fake"},
                    },
                )
                self.assertEqual(custom["id"], "doc-reviewer")
                fetched = request_json(f"{base_url}/profiles/doc-reviewer")
                self.assertEqual(fetched["version"], 1)

                mission = request_json(
                    f"{base_url}/missions",
                    method="POST",
                    payload={
                        "goal": "Exercise the mission API",
                        "strategy": "custom",
                        "adapter": "fake",
                        "tasks": [
                            {"id": "plan", "profile": "planner", "prompt": "plan"},
                            {
                                "id": "report",
                                "profile": "doc-reviewer",
                                "depends_on": ["plan"],
                                "prompt": "report",
                            },
                        ],
                    },
                )
                mission_id = mission["mission_id"]
                deadline = time.time() + 15
                current: dict[str, Any] = {}
                while time.time() < deadline:
                    current = request_json(f"{base_url}/missions/{mission_id}")
                    if current["status"] == "completed":
                        break
                    time.sleep(0.05)
                self.assertEqual(current["status"], "completed")
                self.assertEqual(len(current["tasks"]), 2)
                self.assertTrue(all(task["run_id"] for task in current["tasks"]))

                events = request_json(f"{base_url}/missions/{mission_id}/events.json")
                self.assertIn("mission.completed", [event["type"] for event in events["events"]])
                artifacts = request_json(f"{base_url}/missions/{mission_id}/artifacts")
                artifact_names = {artifact["name"] for artifact in artifacts["artifacts"]}
                self.assertIn("mission_manifest.json", artifact_names)
                self.assertIn("final_report.md", artifact_names)
                missions = request_json(f"{base_url}/missions")
                self.assertEqual(missions["missions"][0]["mission_id"], mission_id)

    def test_acp_a2a_and_temporal_poc_http_api(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with running_runtime(artifact_root=Path(tmp), worker_capacity=2) as base_url:
                acp = request_json(
                    f"{base_url}/acp",
                    method="POST",
                    payload={"jsonrpc": "2.0", "id": 1, "method": "initialize"},
                )
                self.assertEqual(acp["result"]["protocol"], "acp-poc")
                self.assertIn("executor.list", acp["result"]["methods"])
                run = request_json(
                    f"{base_url}/acp",
                    method="POST",
                    payload={
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "run.create",
                        "params": {"prompt": "hello acp", "adapter": "fake"},
                    },
                )
                run_id = run["result"]["run_id"]
                deadline = time.time() + 3
                run_status: dict[str, Any] = {}
                while time.time() < deadline:
                    run_status = request_json(
                        f"{base_url}/acp",
                        method="POST",
                        payload={
                            "jsonrpc": "2.0",
                            "id": 3,
                            "method": "run.status",
                            "params": {"run_id": run_id},
                        },
                    )
                    if run_status["result"]["status"] == "completed":
                        break
                    time.sleep(0.05)
                self.assertEqual(run_status["result"]["status"], "completed")
                executor_result = request_json(
                    f"{base_url}/acp",
                    method="POST",
                    payload={"jsonrpc": "2.0", "id": 31, "method": "executor.list"},
                )
                self.assertIn("executor_registry", executor_result["result"])
                cost_result = request_json(
                    f"{base_url}/acp",
                    method="POST",
                    payload={"jsonrpc": "2.0", "id": 32, "method": "cost.status"},
                )
                self.assertIn("monthly_estimated_cost_usd", cost_result["result"])
                access_result = request_json(
                    f"{base_url}/acp",
                    method="POST",
                    payload={"jsonrpc": "2.0", "id": 33, "method": "access.policy"},
                )
                self.assertIn("roles", access_result["result"])
                permissions_result = request_json(
                    f"{base_url}/acp",
                    method="POST",
                    payload={
                        "jsonrpc": "2.0",
                        "id": 34,
                        "method": "run.permissions",
                        "params": {"run_id": run_id},
                    },
                )
                self.assertIn("permissions", permissions_result["result"])

                card = request_json(f"{base_url}/.well-known/agent-card.json")
                self.assertEqual(card["protocol"], "a2a-poc")
                self.assertIn("protocolVersion", card)
                self.assertIn("executors", card["endpoints"])
                task = request_json(
                    f"{base_url}/a2a/tasks",
                    method="POST",
                    payload={"goal": "external gateway task", "adapter": "fake"},
                )
                task_id = task["task_id"]
                deadline = time.time() + 5
                task_status: dict[str, Any] = {}
                while time.time() < deadline:
                    task_status = request_json(f"{base_url}/a2a/tasks/{task_id}")
                    if task_status["status"] == "completed":
                        break
                    time.sleep(0.05)
                self.assertEqual(task_status["status"], "completed")
                plan = request_json(f"{base_url}/temporal/workflows/missions/{task_id}/plan")
                self.assertEqual(plan["workflow"], "MissionWorkflow")
                run_plan = request_json(f"{base_url}/temporal/workflows/runs/{run_id}/plan")
                self.assertEqual(run_plan["workflow"], "AgentRunWorkflow")
                task_events = request_json(f"{base_url}/a2a/tasks/{task_id}/events.json")
                self.assertIn("events", task_events)
                task_artifacts = request_json(f"{base_url}/a2a/tasks/{task_id}/artifacts")
                self.assertIn("artifacts", task_artifacts)

    def test_ops_metrics_backups_drills_and_p5_evaluations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with running_runtime(artifact_root=Path(tmp), worker_capacity=1) as base_url:
                run = request_json(
                    f"{base_url}/runs",
                    method="POST",
                    payload={"prompt": "ops smoke", "adapter": "fake"},
                )
                deadline = time.time() + 5
                while time.time() < deadline:
                    current = request_json(f"{base_url}/runs/{run['run_id']}")
                    if current["status"] == "completed":
                        break
                    time.sleep(0.05)

                metrics = request_json(f"{base_url}/metrics.json")
                self.assertGreaterEqual(metrics["runs"]["total"], 1)
                self.assertIn("latency_seconds", metrics)
                status = request_json(f"{base_url}/ops/status")
                self.assertIn("security", status)
                self.assertIn("metrics", status)
                drills = request_json(f"{base_url}/ops/drills")
                self.assertIn(drills["status"], {"pass", "warn"})
                p5 = request_json(f"{base_url}/p5/evaluations")
                component_ids = {component["id"] for component in p5["components"]}
                self.assertIn("acp-streamable-http", component_ids)
                self.assertIn("a2a-gateway", component_ids)

                created = request_json(f"{base_url}/ops/backups", method="POST", payload={})
                backup_name = created["backup"]["name"]
                backups = request_json(f"{base_url}/ops/backups")
                self.assertIn(backup_name, {backup["name"] for backup in backups["backups"]})
                backup_body = request_binary(f"{base_url}/ops/backups/{backup_name}")
                self.assertGreater(len(backup_body), 0)
                with self.assertRaises(urllib.error.HTTPError) as bad_backup:
                    request_binary(f"{base_url}/ops/backups/%2E%2E%2Fbad.tar.gz")
                self.assertEqual(bad_backup.exception.code, HTTPStatus.BAD_REQUEST)
                with self.assertRaises(urllib.error.HTTPError) as missing_backup:
                    request_binary(f"{base_url}/ops/backups/missing.tar.gz")
                self.assertEqual(missing_backup.exception.code, HTTPStatus.NOT_FOUND)

    def test_sse_reconnect_and_gap_detection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with running_runtime(artifact_root=Path(tmp)) as base_url:
                run = request_json(
                    f"{base_url}/runs",
                    method="POST",
                    payload={"prompt": "hello reconnect runtime", "adapter": "fake"},
                )
                initial_events = read_sse(f"{base_url}/runs/{run['run_id']}/events")
                self.assertGreater(len(initial_events), 2)

                replayed = read_sse(
                    f"{base_url}/runs/{run['run_id']}/events",
                    headers={"Last-Event-ID": "2"},
                )
                self.assertTrue(replayed)
                self.assertGreater(replayed[0]["data"]["sequence"], 2)

                gap = read_sse(
                    f"{base_url}/runs/{run['run_id']}/events",
                    headers={"Last-Event-ID": "999"},
                )
                self.assertEqual(gap[0]["event"], "event.gap_detected")
                self.assertEqual(gap[0]["data"]["data"]["requested_last_sequence"], 999)

    def test_permission_resolution_endpoint_writes_audit_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with running_runtime(artifact_root=Path(tmp)) as base_url:
                run = request_json(
                    f"{base_url}/runs",
                    method="POST",
                    payload={"prompt": "permission audit", "adapter": "fake"},
                )
                accepted = request_json(
                    f"{base_url}/runs/{run['run_id']}/permissions/perm-1",
                    method="POST",
                    payload={
                        "decision": "approve",
                        "decided_by": "tester",
                        "reason": "unit test",
                    },
                )
                self.assertTrue(accepted["accepted"])
                events = read_sse(f"{base_url}/runs/{run['run_id']}/events")
                self.assertIn("permission.resolved", [event["event"] for event in events])
                run_dir = Path(tmp) / run["run_id"]
                permission_artifacts = sorted(run_dir.glob("permission.resolved_*.json"))
                self.assertEqual(len(permission_artifacts), 1)

    def test_qwen_adapter_maps_fake_daemon_events(self) -> None:
        with running_fake_qwen() as qwen_url:
            with tempfile.TemporaryDirectory() as tmp:
                with running_runtime(artifact_root=Path(tmp), qwen_url=qwen_url) as base_url:
                    run = request_json(
                        f"{base_url}/runs",
                        method="POST",
                        payload={"prompt": "hello qwen", "adapter": "qwen"},
                    )
                    deadline = time.time() + 3
                    current: dict[str, Any] = {}
                    while time.time() < deadline:
                        current = request_json(f"{base_url}/runs/{run['run_id']}")
                        if current["status"] == "completed":
                            break
                        time.sleep(0.05)
                    self.assertEqual(current["status"], "completed")
                    events = read_sse(f"{base_url}/runs/{run['run_id']}/events")
                    event_names = [event["event"] for event in events]
                    self.assertIn("message.delta", event_names)
                    raw = (Path(tmp) / run["run_id"] / "raw_events.jsonl").read_text(
                        encoding="utf-8"
                    )
                    self.assertIn("agent_message_chunk", raw)
                    self.assertIn("turn_complete", raw)
                    request_json(
                        f"{base_url}/runs/{run['run_id']}/permissions/perm-qwen",
                        method="POST",
                        payload={
                            "decision": "approve",
                            "decided_by": "tester",
                            "option_id": "allow_once",
                        },
                    )
                    self.assertEqual(
                        FakeQwenHandler.permission_response,
                        {"outcome": {"outcome": "selected", "optionId": "allow_once"}},
                    )

    def test_qwen_adapter_extracts_structured_gate_from_final_text(self) -> None:
        gate_text = (
            "review done\n"
            "```json\n"
            '{"decision":"pass","severity":"none","reason":"qwen reviewer passed","findings":[]}'
            "\n```"
        )
        with running_fake_qwen(message_text=gate_text) as qwen_url:
            with tempfile.TemporaryDirectory() as tmp:
                with running_runtime(artifact_root=Path(tmp), qwen_url=qwen_url) as base_url:
                    reviewer = request_json(f"{base_url}/profiles/reviewer")
                    run = request_json(
                        f"{base_url}/runs",
                        method="POST",
                        payload={
                            "prompt": "review and emit gate",
                            "adapter": "qwen",
                            "metadata": {"profile_snapshot": reviewer},
                        },
                    )
                    deadline = time.time() + 3
                    current: dict[str, Any] = {}
                    while time.time() < deadline:
                        current = request_json(f"{base_url}/runs/{run['run_id']}")
                        if current["status"] == "completed":
                            break
                        time.sleep(0.05)
                    self.assertEqual(current["status"], "completed")
                    gate_path = Path(tmp) / run["run_id"] / "review_gate.json"
                    self.assertTrue(gate_path.exists())
                    gate = json.loads(gate_path.read_text(encoding="utf-8"))
                    self.assertFalse(gate["blocks"])


class running_runtime:
    def __init__(
        self,
        artifact_root: Path | None = None,
        token: str | None = None,
        qwen_url: str | None = None,
        worker_capacity: int | None = None,
        login_user: str | None = None,
        login_password: str | None = None,
        bootstrap_email: str | None = None,
        bootstrap_password: str | None = None,
        bootstrap_name: str | None = None,
        session_secret: str | None = None,
    ):
        self.tmp = tempfile.TemporaryDirectory() if artifact_root is None else None
        self.artifact_root = artifact_root or Path(self.tmp.name)
        self.server = build_server(
            "127.0.0.1",
            0,
            self.artifact_root,
            auth_config=AuthConfig(
                token=token,
                login_user=login_user,
                login_password=login_password,
                bootstrap_email=bootstrap_email,
                bootstrap_password=bootstrap_password,
                bootstrap_name=bootstrap_name,
                session_secret=session_secret,
            ),
            qwen_base_url=qwen_url,
            worker_capacity=worker_capacity,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> str:
        self.thread.start()
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        if self.tmp:
            self.tmp.cleanup()


class running_fake_qwen:
    def __init__(self, message_text: str | None = None):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeQwenHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.message_text = message_text or "hello from qwen"

    def __enter__(self) -> str:
        FakeQwenHandler.cancelled = False
        FakeQwenHandler.permission_response = None
        FakeQwenHandler.prompt_event = threading.Event()
        FakeQwenHandler.event_connections = 0
        FakeQwenHandler.message_text = self.message_text
        self.thread.start()
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)


class FakeQwenHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    cancelled = False
    permission_response: dict[str, Any] | None = None
    prompt_event = threading.Event()
    event_connections = 0
    message_text = "hello from qwen"

    def do_GET(self) -> None:
        if self.path == "/health":
            self.write_json({"ok": True})
            return
        if self.path == "/session/session-1/events":
            FakeQwenHandler.event_connections += 1
            FakeQwenHandler.prompt_event.wait(timeout=2)
            self.send_response(HTTPStatus.OK)
            self.send_header("content-type", "text/event-stream")
            self.send_header("connection", "close")
            self.end_headers()
            self.write_sse(
                1,
                "session_update",
                {
                    "id": 1,
                    "v": 1,
                    "type": "session_update",
                    "data": {
                        "sessionId": "session-1",
                        "update": {
                            "sessionUpdate": "agent_message_chunk",
                            "content": {
                                "type": "text",
                                "text": FakeQwenHandler.message_text,
                            },
                        },
                    },
                },
            )
            self.write_sse(
                2,
                "turn_complete",
                {
                    "id": 2,
                    "v": 1,
                    "type": "turn_complete",
                    "data": {"promptId": "prompt-1"},
                },
            )
            return
        self.write_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if self.path == "/session":
            self.read_body()
            self.write_json(
                {"sessionId": "session-1", "workspaceCwd": "/tmp/workspace", "attached": False}
            )
            return
        if self.path == "/session/session-1/prompt":
            self.read_body()
            FakeQwenHandler.prompt_event.set()
            self.write_json({"accepted": True, "promptId": "prompt-1"}, status=HTTPStatus.ACCEPTED)
            return
        if self.path == "/session/session-1/cancel":
            FakeQwenHandler.cancelled = True
            self.read_body()
            self.write_json({"cancelled": True})
            return
        if self.path == "/permission/perm-qwen":
            FakeQwenHandler.permission_response = json.loads(
                self.read_body().decode("utf-8")
            )
            self.write_json({"ok": True})
            return
        self.write_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)

    def read_body(self) -> bytes:
        length = int(self.headers.get("content-length", "0") or "0")
        return self.rfile.read(length) if length else b""

    def write_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def write_sse(self, event_id: int, event_name: str, payload: dict[str, Any]) -> None:
        self.wfile.write(
            (
                f"id: {event_id}\n"
                f"event: {event_name}\n"
                f"data: {json.dumps(payload)}\n\n"
            ).encode("utf-8")
        )
        self.wfile.flush()

    def log_message(self, fmt: str, *args: Any) -> None:
        return


def request_json(
    url: str,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    if payload is not None:
        request.add_header("content-type", "application/json")
    with urllib.request.urlopen(request, timeout=5) as response:
        parsed = json.loads(response.read().decode("utf-8"))
        assert isinstance(parsed, dict)
        return parsed


def request_raw(
    url: str,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> urllib.response.addinfourl:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    if payload is not None:
        request.add_header("content-type", "application/json")
    return urllib.request.urlopen(request, timeout=5)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def request_no_redirect(
    url: str,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> urllib.response.addinfourl:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    if payload is not None:
        request.add_header("content-type", "application/json")
    opener = urllib.request.build_opener(NoRedirect)
    try:
        return opener.open(request, timeout=5)
    except urllib.error.HTTPError as response:
        return response


def request_text(url: str, headers: dict[str, str] | None = None) -> str:
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.read().decode("utf-8")


def request_binary(url: str, headers: dict[str, str] | None = None) -> bytes:
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.read()


def wait_for_run_status(base_url: str, run_id: str, status: str) -> dict[str, Any]:
    deadline = time.time() + 5
    last: dict[str, Any] | None = None
    while time.time() < deadline:
        last = request_json(f"{base_url}/runs/{run_id}")
        if last.get("status") == status:
            return last
        time.sleep(0.05)
    raise AssertionError(f"run {run_id} did not reach {status}; last={last}")


def read_sse(url: str, headers: dict[str, str] | None = None) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=5) as response:
        event_name: str | None = None
        data_lines: list[str] = []
        for raw_line in response:
            line = raw_line.decode("utf-8").rstrip("\n")
            if line.startswith("event:"):
                event_name = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].strip())
            elif line == "" and data_lines:
                events.append({"event": event_name, "data": json.loads("\n".join(data_lines))})
                data_lines = []
                event_name = None
    return events


if __name__ == "__main__":
    unittest.main()
