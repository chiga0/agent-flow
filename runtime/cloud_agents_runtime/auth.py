from __future__ import annotations

import hmac
from dataclasses import dataclass


@dataclass(frozen=True)
class AuthConfig:
    token: str | None = None
    protect_health: bool = False

    @property
    def enabled(self) -> bool:
        return bool(self.token)

    def is_public_path(self, path: str) -> bool:
        return path == "/health" and not self.protect_health


def is_authorized(config: AuthConfig, path: str, authorization: str | None) -> bool:
    if not config.enabled or config.is_public_path(path):
        return True
    expected = f"Bearer {config.token}"
    return bool(authorization) and hmac.compare_digest(authorization, expected)

