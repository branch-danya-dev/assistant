"""SQLite canonical state, transactional migrations, OS-released execution lock."""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import uuid4

from .config import AgentError, Paths


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def uid() -> str:
    return str(uuid4())


def encode(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False)


MIGRATIONS = [
    """
    CREATE TABLE tasks(id TEXT PRIMARY KEY, state TEXT NOT NULL, document TEXT NOT NULL,
                       scope TEXT NOT NULL, plan TEXT NOT NULL DEFAULT '[]', result TEXT);
    CREATE TABLE events(task_id TEXT NOT NULL REFERENCES tasks(id), sequence INTEGER NOT NULL,
                        document TEXT NOT NULL, PRIMARY KEY(task_id,sequence));
    CREATE TABLE actions(id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id),
                         ordinal INTEGER NOT NULL, request TEXT NOT NULL, digest TEXT NOT NULL,
                         effect TEXT NOT NULL, resource TEXT NOT NULL, status TEXT NOT NULL,
                         approval_id TEXT, result TEXT, attempts INTEGER NOT NULL DEFAULT 0,
                         UNIQUE(task_id,ordinal));
    CREATE TABLE approvals(id TEXT PRIMARY KEY, action_id TEXT NOT NULL REFERENCES actions(id),
                           document TEXT NOT NULL);
    CREATE TABLE controls(name TEXT PRIMARY KEY, value TEXT NOT NULL);
    INSERT INTO controls VALUES ('stopped','0');
    CREATE TABLE memory(id TEXT PRIMARY KEY, project_id TEXT, sensitivity TEXT NOT NULL,
                        statement TEXT NOT NULL, document TEXT NOT NULL,
                        removed INTEGER NOT NULL DEFAULT 0);
    CREATE INDEX memory_scope ON memory(project_id,sensitivity,removed);
    CREATE VIRTUAL TABLE memory_fts USING fts5(id UNINDEXED, statement, tokenize='unicode61');
    CREATE TABLE memory_events(id TEXT PRIMARY KEY, kind TEXT NOT NULL, record_id TEXT NOT NULL,
                               timestamp TEXT NOT NULL);
    """,
    """
    CREATE TABLE plan_revisions(task_id TEXT NOT NULL REFERENCES tasks(id),
                                revision INTEGER NOT NULL, document TEXT NOT NULL,
                                PRIMARY KEY(task_id,revision));
    """,
    # v3 adds preview inventory and terminal partial state; old applications must refuse v3.
    "CREATE TABLE approval_previews(name TEXT PRIMARY KEY, identity TEXT NOT NULL, expires REAL NOT NULL);",
    """
    CREATE TABLE data_admissions(kind TEXT NOT NULL, object_id TEXT NOT NULL,
        project_id TEXT NOT NULL, digest TEXT NOT NULL, classification TEXT NOT NULL,
        owner TEXT NOT NULL, provenance TEXT NOT NULL, reviewed_at TEXT NOT NULL,
        expires_at TEXT NOT NULL, PRIMARY KEY(kind,object_id));
    CREATE TABLE sensitive_inventory(id TEXT PRIMARY KEY, kind TEXT NOT NULL,
        project_id TEXT NOT NULL, locator TEXT NOT NULL, locator_key TEXT NOT NULL,
        classification TEXT NOT NULL, owner TEXT NOT NULL, provenance TEXT NOT NULL,
        reviewed_at TEXT, expires_at TEXT NOT NULL,
        UNIQUE(kind,project_id,locator_key));
    CREATE TABLE data_reviews(id TEXT PRIMARY KEY, kind TEXT NOT NULL, object_id TEXT NOT NULL,
        digest TEXT NOT NULL, classification TEXT NOT NULL, reviewed_at TEXT NOT NULL,
        expires_at TEXT NOT NULL);
    """
]


class Store:
    def __init__(self, paths: Paths):
        paths.require()
        self.paths = paths
        self.executing = False
        self.connection = sqlite3.connect(paths.file("db", "agent.sqlite3"),
                                          timeout=5, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        try:
            version = self.connection.execute("PRAGMA user_version").fetchone()[0]
            if version > len(MIGRATIONS):
                raise AgentError("database_version_newer_than_application")
            if version < 0 or (version == 0 and self.connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table'").fetchone()):
                raise AgentError("database_version_invalid")
            self.migration_backup = None
            if version < len(MIGRATIONS):
                with self.execution_lock():
                    version = self.connection.execute("PRAGMA user_version").fetchone()[0]
                    if not 0 <= version <= len(MIGRATIONS):
                        raise AgentError("database_version_invalid")
                    if version:
                        self.migration_backup = self.backup()
                    if version < len(MIGRATIONS):
                        self.connection.executescript("BEGIN IMMEDIATE;\n" +
                            "\n".join(MIGRATIONS[version:]) +
                            f"\nPRAGMA user_version={len(MIGRATIONS)};\nCOMMIT;")
            self.connection.execute("PRAGMA journal_mode=WAL")
            self.connection.execute("PRAGMA synchronous=FULL")
        except BaseException:
            self.connection.rollback()
            self.connection.close()
            raise

    def close(self):
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    @contextmanager
    def transaction(self):
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield self.connection
            self.connection.commit()
        except BaseException:
            self.connection.rollback()
            raise

    @contextmanager
    def execution_lock(self):
        """One executor/recovery at a time; separate stop/inspect connections remain usable."""
        file = self.paths.file("db", "executor.lock").open("a+b")
        try:
            file.seek(0, os.SEEK_END)
            if file.tell() == 0:
                file.write(b"0")
                file.flush()
            file.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise AgentError("executor_busy") from None
            try:
                self.executing = True
                yield
            finally:
                self.executing = False
                file.seek(0)
                if os.name == "nt":
                    msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(file.fileno(), fcntl.LOCK_UN)
        finally:
            file.close()

    def backup(self) -> str:
        path = self.paths.file("backups", f"agent-{uid()}.sqlite3")
        relative = path.relative_to(self.paths.root).as_posix()
        target = sqlite3.connect(path)
        try:
            self.connection.backup(target)
            if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise AgentError("backup_integrity_failed")
        finally:
            target.close()
        return relative
