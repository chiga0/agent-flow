from __future__ import annotations

import os
import shlex
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path


@dataclass
class QwenSupervisorConfig:
    command: list[str]
    base_url: str
    cwd: Path | None = None
    startup_timeout_seconds: float = 20.0


class QwenServeProcess:
    def __init__(self, config: QwenSupervisorConfig):
        self.config = config
        self.process: subprocess.Popen[str] | None = None

    @classmethod
    def from_command(
        cls,
        command: list[str],
        base_url: str,
        cwd: Path | None = None,
        startup_timeout_seconds: float = 20.0,
    ) -> "QwenServeProcess":
        return cls(
            QwenSupervisorConfig(
                command=command,
                base_url=base_url,
                cwd=cwd,
                startup_timeout_seconds=startup_timeout_seconds,
            )
        )

    def start(self) -> None:
        if self.process and self.process.poll() is None:
            return
        self.process = subprocess.Popen(
            self.config.command,
            cwd=str(self.config.cwd) if self.config.cwd else None,
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.wait_until_ready()

    def stop(self) -> None:
        if not self.process or self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)

    def wait_until_ready(self) -> None:
        deadline = time.monotonic() + self.config.startup_timeout_seconds
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            if self.process and self.process.poll() is not None:
                raise RuntimeError(f"qwen serve exited early with code {self.process.returncode}")
            try:
                with urllib.request.urlopen(
                    f"{self.config.base_url}/health", timeout=1
                ) as response:
                    if response.status < 500:
                        return
            except urllib.error.HTTPError as exc:
                if exc.code < 500:
                    return
                last_error = exc
            except (urllib.error.URLError, TimeoutError) as exc:
                last_error = exc
            time.sleep(0.25)
        raise RuntimeError(f"qwen serve did not become healthy: {last_error}")


def qwen_supervisor_from_env() -> QwenServeProcess | None:
    command = os.environ.get("QWEN_SERVE_COMMAND")
    if not command:
        return None
    base_url = os.environ.get("QWEN_SERVE_URL") or "http://127.0.0.1:4170"
    cwd = os.environ.get("QWEN_SERVE_CWD")
    timeout = float(os.environ.get("QWEN_SERVE_STARTUP_TIMEOUT", "20"))
    return QwenServeProcess(
        QwenSupervisorConfig(
            command=shlex.split(command),
            base_url=base_url,
            cwd=Path(cwd) if cwd else None,
            startup_timeout_seconds=timeout,
        )
    )
