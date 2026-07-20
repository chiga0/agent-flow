from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from runtime.cloud_agents_runtime.database import RuntimeDatabase


class RuntimeDatabaseTest(unittest.TestCase):
    def test_context_manager_closes_sqlite_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with RuntimeDatabase(Path(tmp) / "context.db") as database:
                connection = database._connection
                database.execute("CREATE TABLE sample (id TEXT PRIMARY KEY)")
                database.commit()
            with self.assertRaises(sqlite3.ProgrammingError):
                connection.execute("SELECT 1")

    def test_sqlite_backend_executes_common_sql(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database = RuntimeDatabase(Path(tmp) / "test.db")
            database.executescript(
                "CREATE TABLE values_table (id TEXT PRIMARY KEY, value TEXT);"
            )
            database.execute(
                "INSERT OR IGNORE INTO values_table (id, value) VALUES (?, ?)",
                ("one", "first"),
            )
            database.execute(
                "INSERT OR IGNORE INTO values_table (id, value) VALUES (?, ?)",
                ("one", "ignored"),
            )
            database.commit()
            row = database.execute(
                "SELECT value FROM values_table WHERE id = ?", ("one",)
            ).fetchone()
            self.assertEqual(row["value"], "first")
            self.assertEqual(database.for_update_skip_locked(), "")
            database.close()

    def test_postgres_translation_and_lock_clause(self) -> None:
        database = RuntimeDatabase.__new__(RuntimeDatabase)
        database.dialect = "postgres"
        database._connection = Mock()
        self.assertEqual(
            database._sql("SELECT * FROM sample WHERE id = ?"),
            "SELECT * FROM sample WHERE id = %s",
        )
        self.assertEqual(
            database._sql("INSERT OR IGNORE INTO sample (id) VALUES (?)"),
            "INSERT INTO sample (id) VALUES (%s) ON CONFLICT DO NOTHING",
        )
        self.assertEqual(database.for_update_skip_locked(), " FOR UPDATE OF a SKIP LOCKED")
        database.executescript("SELECT 1; SELECT 2;")
        database.task_lock("task-one")
        database.commit()
        database.rollback()
        database.close()
        database.close()
        self.assertEqual(database._connection.execute.call_count, 3)
        database._connection.commit.assert_called_once_with()
        database._connection.rollback.assert_called_once_with()
        database._connection.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
