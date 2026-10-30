import os
import shutil
import sqlite3
from pathlib import Path
from unittest.mock import patch

from support import RuntimeCase
from personal_agent.config import AgentError, Paths
from personal_agent.storage import Store


class StorageTests(RuntimeCase):
    def test_missing_root_and_escape(self):
        with self.assertRaises(AgentError):
            Paths("relative")
        with self.assertRaises(AgentError):
            Store(Paths(Path(self.temp.name) / "absent"))
        for value in ("../escape", "C:/secret", "/absolute", "x:stream", "NUL", "x/./y"):
            with self.subTest(value=value), self.assertRaises(AgentError):
                self.paths.under(value)
        with patch.dict(os.environ, {"ASSISTANT_ROOT": str(self.paths.root)}):
            self.assertEqual(Paths().root, self.paths.root)

    def test_scn009_relocation_and_consistent_backup(self):
        task = self.task()
        backup = self.store.backup()
        other = Paths(Path(self.temp.name) / "relocated")
        other.bootstrap()
        shutil.copyfile(self.paths.under(backup), other.under("data/db/agent.sqlite3"))
        with Store(other) as restored:
            row = restored.connection.execute("SELECT id FROM tasks").fetchone()
            self.assertEqual(row[0], task)
            self.assertEqual(restored.connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        for name in self.paths.config["layout"]:
            self.assertEqual(self.paths.directory(name).relative_to(self.paths.root),
                             other.directory(name).relative_to(other.root))
        self.assertEqual(other.directory("models_ollama"), other.root / "models/ollama")

    def test_migration_is_idempotent_and_future_schema_rejected(self):
        with Store(self.paths) as second:
            self.assertEqual(second.connection.execute("PRAGMA user_version").fetchone()[0], 1)
            second.connection.execute("PRAGMA user_version=999")
        with self.assertRaises(AgentError):
            Store(self.paths)

    def test_execution_lock_excludes_second_worker(self):
        with self.store.execution_lock():
            with Store(self.paths) as second:
                with self.assertRaises(AgentError):
                    with second.execution_lock():
                        self.fail("Second executor acquired lock")
                second.connection.execute("UPDATE controls SET value='1'")
                self.assertTrue(self.journal.stopped())

    def test_migration_rollback(self):
        path = self.paths.under("data/db/failure.sqlite3")
        connection = sqlite3.connect(path)
        try:
            with self.assertRaises(sqlite3.Error):
                connection.executescript("BEGIN; CREATE TABLE example(id); INVALID SQL; COMMIT;")
            connection.rollback()
            self.assertIsNone(connection.execute(
                "SELECT name FROM sqlite_master WHERE name='example'").fetchone())
        finally:
            connection.close()
