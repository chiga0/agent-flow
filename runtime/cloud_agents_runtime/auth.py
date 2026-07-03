from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from http import cookies
from typing import Any


SESSION_COOKIE = "cloud_agents_session"
PASSWORD_HASH_ALGORITHM = "pbkdf2_sha256"
PASSWORD_HASH_ITERATIONS = 210_000
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass(frozen=True)
class AuthConfig:
    token: str | None = None
    protect_health: bool = False
    login_user: str | None = None
    login_password: str | None = None
    bootstrap_email: str | None = None
    bootstrap_password: str | None = None
    bootstrap_name: str | None = None
    session_secret: str | None = None
    session_ttl_seconds: int = 12 * 60 * 60

    @property
    def enabled(self) -> bool:
        return bool(self.token)

    @property
    def login_enabled(self) -> bool:
        return bool(self.bootstrap_password_value and self.bootstrap_email_value)

    @property
    def session_secret_value(self) -> str | None:
        return self.session_secret or self.token

    @property
    def bootstrap_password_value(self) -> str | None:
        return self.bootstrap_password or self.login_password

    @property
    def bootstrap_email_value(self) -> str | None:
        configured = self.bootstrap_email or self.login_user
        if not configured:
            return None
        if "@" in configured:
            return normalize_email(configured)
        return "cloudagents@local.test"

    @property
    def bootstrap_display_name(self) -> str | None:
        return self.bootstrap_name or self.login_user or self.bootstrap_email_value

    def is_public_path(self, path: str) -> bool:
        if path == "/health" and not self.protect_health:
            return True
        if path in {"/", "/ui", "/auth/session", "/auth/login", "/auth/logout"}:
            return True
        return path.startswith("/assets/")

    def login_matches(self, username: Any, password: Any) -> bool:
        if not self.login_enabled:
            return False
        login_id = self.resolve_login_email(username)
        return (
            isinstance(password, str)
            and login_id == self.bootstrap_email_value
            and hmac.compare_digest(password, self.bootstrap_password_value or "")
        )

    def issue_session_cookie(
        self,
        session_token: str,
        *,
        cookie_path: str = "/",
        secure: bool = False,
    ) -> str:
        return _cookie_header(
            session_token,
            max_age=self.session_ttl_seconds,
            path=cookie_path,
            secure=secure,
        )

    def clear_session_cookie(self, *, cookie_path: str = "/", secure: bool = False) -> str:
        return _cookie_header("", max_age=0, path=cookie_path, secure=secure)

    def session_token(self, cookie_header: str | None) -> str | None:
        if not cookie_header:
            return None
        try:
            parsed = cookies.SimpleCookie(cookie_header)
        except cookies.CookieError:
            return None
        morsel = parsed.get(SESSION_COOKIE)
        if not morsel or not morsel.value:
            return None
        return morsel.value

    def session_status(self, identity: dict[str, Any] | None) -> dict[str, Any]:
        principal = str(identity["principal_id"]) if identity else None
        return {
            "authenticated": bool(identity) or not self.login_enabled,
            "login_required": self.login_enabled,
            "principal": (
                {
                    "id": principal or "local-dev",
                    "email": identity.get("email") if identity else None,
                    "display_name": (
                        str(identity.get("display_name") or principal)
                        if identity
                        else "Local development"
                    ),
                    "roles": list(identity.get("roles") or ["owner"]) if identity else ["owner"],
                }
                if identity or not self.login_enabled
                else None
            ),
            "auth_mode": "local_email" if self.login_enabled else "disabled",
        }

    def resolve_login_email(self, login_id: Any) -> str | None:
        if not isinstance(login_id, str) or not login_id.strip():
            return None
        candidate = login_id.strip()
        if "@" in candidate:
            return normalize_email(candidate)
        if self.login_user and hmac.compare_digest(candidate, self.login_user):
            return self.bootstrap_email_value
        return None


def is_authorized(config: AuthConfig, path: str, authorization: str | None) -> bool:
    if not config.enabled or config.is_public_path(path):
        return True
    expected = f"Bearer {config.token}"
    return bool(authorization) and hmac.compare_digest(authorization, expected)


def normalize_email(value: str) -> str:
    email = value.strip().lower()
    if len(email) > 254 or not EMAIL_RE.match(email):
        raise ValueError("email is invalid")
    return email


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PASSWORD_HASH_ITERATIONS,
    )
    return "$".join(
        [
            PASSWORD_HASH_ALGORITHM,
            str(PASSWORD_HASH_ITERATIONS),
            _b64encode_bytes(salt),
            _b64encode_bytes(digest),
        ]
    )


def verify_password(password: Any, stored_hash: str) -> bool:
    if not isinstance(password, str):
        return False
    try:
        algorithm, iterations_raw, salt_raw, digest_raw = stored_hash.split("$", 3)
        if algorithm != PASSWORD_HASH_ALGORITHM:
            return False
        iterations = int(iterations_raw)
        salt = _b64decode_bytes(salt_raw)
        expected = _b64decode_bytes(digest_raw)
    except (ValueError, TypeError):
        return False
    actual = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return hmac.compare_digest(actual, expected)


def new_session_token() -> str:
    return f"cas_{secrets.token_urlsafe(32)}"


def session_expiry(ttl_seconds: int) -> str:
    expires = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
    return expires.isoformat(timespec="milliseconds")


def _cookie_header(value: str, *, max_age: int, path: str, secure: bool) -> str:
    cookie_path = path if path.startswith("/") else "/"
    parts = [
        f"{SESSION_COOKIE}={value}",
        f"Max-Age={max_age}",
        f"Path={cookie_path}",
        "HttpOnly",
        "SameSite=Lax",
    ]
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


def _b64encode_bytes(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode_bytes(value: str) -> bytes:
    padded = value + ("=" * (-len(value) % 4))
    return base64.urlsafe_b64decode(padded.encode("ascii"))
