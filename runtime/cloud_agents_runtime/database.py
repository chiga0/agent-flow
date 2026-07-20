from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any, Iterable


INSERT_OR_IGNORE_RE = re.compile(r"\bINSERT\s+OR\s+IGNORE\s+INTO\b", re.IGNORECASE)


class RuntimeDatabase:
    """DB-API bridge for the V2 SQLite and PostgreSQL domain stores."""

    def __init__(self, sqlite_path: Path, database_url: str | None = None):
        self.dialect = "postgres" if database_url else "sqlite"
        if database_url:
            try:
                import psycopg
                from psycopg.rows import dict_row
            except ModuleNotFoundError as exc:
                raise RuntimeError(
                    "PostgreSQL V2 storage requires the psycopg runtime dependency"
                ) from exc
            self._connection = psycopg.connect(database_url, row_factory=dict_row)
        else:
            connection = sqlite3.connect(sqlite_path, check_same_thread=False)
            connection.row_factory = sqlite3.Row
            self._connection = connection

    def execute(self, sql: str, parameters: Iterable[Any] = ()) -> Any:
        return self._connection.execute(self._sql(sql), tuple(parameters))

    def executescript(self, sql: str) -> None:
        if self.dialect == "sqlite":
            self._connection.executescript(sql)
            return
        for statement in sql.split(";"):
            if statement.strip():
                self.execute(statement)

    def commit(self) -> None:
        self._connection.commit()

    def rollback(self) -> None:
        self._connection.rollback()

    def close(self) -> None:
        self._connection.close()

    def task_lock(self, task_id: str) -> None:
        if self.dialect == "postgres":
            self.execute("SELECT pg_advisory_xact_lock(hashtext(?))", (task_id,))

    def for_update_skip_locked(self) -> str:
        return " FOR UPDATE OF a SKIP LOCKED" if self.dialect == "postgres" else ""

    def _sql(self, sql: str) -> str:
        if self.dialect == "sqlite":
            return sql
        translated = INSERT_OR_IGNORE_RE.sub("INSERT INTO", sql).strip()
        if INSERT_OR_IGNORE_RE.search(sql):
            translated = f"{translated.rstrip(';')} ON CONFLICT DO NOTHING"
        return translated.replace("?", "%s")
