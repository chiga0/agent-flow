#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


ASSET_RE = re.compile(r'(?:src|href)="\.(/assets/[^"]+)"')
TERMINAL_RUN_EVENTS = {"run.completed", "run.failed", "run.cancelled"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Monitor public Cloud Agents Runtime")
    parser.add_argument("--base-url", default=default_base_url())
    parser.add_argument("--basic-user", default=os.environ.get("RUNTIME_BASIC_AUTH_USER"))
    parser.add_argument("--basic-password", default=os.environ.get("RUNTIME_BASIC_AUTH_PASSWORD"))
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--deep-run", action="store_true")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    args = parser.parse_args(argv)

    if not args.base_url:
        print("missing --base-url or RUNTIME_PUBLIC_URL/RUNTIME_PUBLIC_HOST", file=sys.stderr)
        return 2
    if not args.basic_password:
        print("missing --basic-password or RUNTIME_BASIC_AUTH_PASSWORD", file=sys.stderr)
        return 2

    monitor = PublicRuntimeMonitor(
        normalize_base_url(args.base_url),
        args.basic_user or "cloudagents",
        args.basic_password,
        args.timeout,
    )
    results = monitor.run(args.deep_run)
    for result in results:
        print(result.render())
    if args.emit_json:
        print(json.dumps({"checks": [result.as_dict() for result in results]}, indent=2))
    failures = [result for result in results if not result.ok]
    if failures:
        message = "; ".join(f"{result.name}: {result.detail}" for result in failures)
        print(f"::error title=Cloud Agents monitor::{message}")
        return 1
    return 0


def default_base_url() -> str | None:
    explicit = os.environ.get("RUNTIME_PUBLIC_URL") or os.environ.get("MONITOR_BASE_URL")
    if explicit:
        return explicit
    host = os.environ.get("RUNTIME_PUBLIC_HOST")
    return f"https://{host}/cloud-agents" if host else None


def normalize_base_url(value: str) -> str:
    value = value.strip()
    if "://" not in value:
        value = f"https://{value}"
    parsed = urllib.parse.urlparse(value)
    path = parsed.path.rstrip("/") or "/cloud-agents"
    normalized = parsed._replace(path=path, params="", query="", fragment="")
    return urllib.parse.urlunparse(normalized).rstrip("/")


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str
    elapsed_ms: int

    def render(self) -> str:
        status = "ok" if self.ok else "fail"
        return f"[{status}] {self.name} ({self.elapsed_ms}ms) {self.detail}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "ok": self.ok,
            "detail": self.detail,
            "elapsed_ms": self.elapsed_ms,
        }


class PublicRuntimeMonitor:
    def __init__(
        self,
        base_url: str,
        basic_user: str,
        basic_password: str,
        timeout: float,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.basic_user = basic_user
        self.basic_password = basic_password
        self.timeout = timeout

    def run(self, deep_run: bool = False) -> list[CheckResult]:
        results = [
            self.check("edge-auth", self.edge_auth),
            self.check("console-html", self.console_html),
            self.check("health", self.health),
            self.check("capabilities", self.capabilities),
            self.check("queue", self.queue),
            self.check("access-policy", self.access_policy),
        ]
        if deep_run:
            results.append(self.check("fake-run", self.fake_run))
        return results

    def check(self, name: str, fn: Any) -> CheckResult:
        started = time.monotonic()
        try:
            detail = fn()
            ok = True
        except Exception as exc:
            detail = str(exc)
            ok = False
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return CheckResult(name, ok, detail, elapsed_ms)

    def edge_auth(self) -> str:
        response = self.request("GET", "/", auth=False, allow_error=True)
        if response.status != 401:
            raise RuntimeError(f"expected 401 challenge, got {response.status}")
        challenge = response.header("www-authenticate")
        if "basic" not in challenge.lower():
            raise RuntimeError("401 response did not include Basic challenge")
        return "public route is protected by Basic Auth"

    def console_html(self) -> str:
        response = self.request("GET", "/", auth=True)
        body = response.text()
        if response.status != 200:
            raise RuntimeError(f"expected 200, got {response.status}")
        if 'id="root"' not in body:
            raise RuntimeError("console root element missing")
        assets = ASSET_RE.findall(body)
        if not assets:
            raise RuntimeError("console asset references missing")
        for asset in assets[:4]:
            asset_response = self.request("GET", asset, auth=True)
            if asset_response.status != 200:
                raise RuntimeError(f"asset {asset} returned {asset_response.status}")
        return f"console loaded with {len(assets)} asset references"

    def health(self) -> str:
        payload = self.json_get("/health")
        if payload.get("ok") is not True:
            raise RuntimeError(f"health not ok: {payload}")
        return f"version={payload.get('version', '-')}"

    def capabilities(self) -> str:
        payload = self.json_get("/capabilities")
        adapters = sorted(payload.get("adapters") or [])
        if "fake" not in adapters:
            raise RuntimeError(f"fake adapter missing: {adapters}")
        features = payload.get("features") or []
        if "reviewer_gate_override" not in features:
            raise RuntimeError("reviewer gate feature missing")
        return f"adapters={','.join(adapters)} features={len(features)}"

    def queue(self) -> str:
        payload = self.json_get("/queue")
        workers = payload.get("workers") or []
        if not workers:
            raise RuntimeError("no workers registered")
        return f"workers={len(workers)} counts={payload.get('counts') or {}}"

    def access_policy(self) -> str:
        payload = self.json_get("/access/policy")
        roles = payload.get("roles") or []
        principal = payload.get("current_principal") or {}
        if not roles:
            raise RuntimeError("roles missing from access policy")
        return f"principal={principal.get('id', '-')} roles={len(roles)}"

    def fake_run(self) -> str:
        run = self.json_request(
            "POST",
            "/runs",
            {"prompt": "public runtime monitor smoke", "adapter": "fake"},
        )
        run_id = str(run["run_id"])
        events = self.sse(f"/runs/{run_id}/events")
        event_names = [event["event"] for event in events]
        if "run.completed" not in event_names:
            raise RuntimeError(f"run did not complete: {event_names}")
        state = self.json_get(f"/runs/{run_id}")
        if state.get("status") != "completed":
            raise RuntimeError(f"run state is {state.get('status')}")
        return f"run={run_id} events={len(event_names)}"

    def json_get(self, path: str) -> dict[str, Any]:
        return self.json_request("GET", path)

    def json_request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = self.request(method, path, auth=True, payload=payload)
        if response.status != 200 and not (method == "POST" and response.status == 201):
            raise RuntimeError(f"{path} returned {response.status}")
        parsed = json.loads(response.text())
        if not isinstance(parsed, dict):
            raise RuntimeError(f"{path} did not return a JSON object")
        return parsed

    def sse(self, path: str) -> list[dict[str, Any]]:
        deadline = time.monotonic() + self.timeout
        response = self.open_request("GET", path, auth=True)
        events: list[dict[str, Any]] = []
        with response:
            event_name: str | None = None
            data_lines: list[str] = []
            for raw_line in response:
                if time.monotonic() > deadline:
                    raise TimeoutError("SSE monitor timed out")
                line = raw_line.decode("utf-8").rstrip("\n")
                if line.startswith("event:"):
                    event_name = line[6:].strip()
                elif line.startswith("data:"):
                    data_lines.append(line[5:].strip())
                elif line == "" and data_lines:
                    data = json.loads("\n".join(data_lines))
                    events.append({"event": event_name, "data": data})
                    if event_name in TERMINAL_RUN_EVENTS:
                        return events
                    event_name = None
                    data_lines = []
        return events

    def request(
        self,
        method: str,
        path: str,
        auth: bool,
        payload: dict[str, Any] | None = None,
        allow_error: bool = False,
    ) -> "Response":
        try:
            with self.open_request(method, path, auth, payload) as response:
                return Response(
                    status=response.status,
                    headers=dict(response.headers.items()),
                    body=response.read(),
                )
        except urllib.error.HTTPError as exc:
            if not allow_error:
                raise
            return Response(exc.code, dict(exc.headers.items()), exc.read())

    def open_request(
        self,
        method: str,
        path: str,
        auth: bool,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{self.base_url}{path if path.startswith('/') else f'/{path}'}"
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(url, data=body, method=method)
        if auth:
            token = f"{self.basic_user}:{self.basic_password}".encode("utf-8")
            encoded = base64.b64encode(token).decode("ascii")
            request.add_header("Authorization", f"Basic {encoded}")
        if payload is not None:
            request.add_header("Content-Type", "application/json")
        return urllib.request.urlopen(request, timeout=self.timeout)


@dataclass(frozen=True)
class Response:
    status: int
    headers: dict[str, str]
    body: bytes

    def header(self, name: str) -> str:
        lowered = name.lower()
        for key, value in self.headers.items():
            if key.lower() == lowered:
                return value
        return ""

    def text(self) -> str:
        return self.body.decode("utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
