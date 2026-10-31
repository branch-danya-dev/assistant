"""Canonical sourced records. Authorization filters precede lexical candidate ranking."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from .config import AgentError, validate
from .data_policy import admit
from .storage import Store, encode, now, uid
from .trust import Trust


class Memory:
    def __init__(self, store: Store):
        self.store = store
        self.db = store.connection

    def add(self, record: dict) -> str:
        admit(record)
        if record.get("sensitivity") not in {"public", "internal", "private"}:
            raise AgentError("memory_sensitivity_denied")
        record = {"sensitivity": "private", "retention_class": "project", **record}
        validate("memory-record", record)
        for field in ("recorded_at", "expires_at", "valid_from", "valid_to"):
            if record.get(field):
                record[field] = datetime.fromisoformat(record[field].replace("Z", "+00:00"))\
                    .astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
        if (not record["source_refs"] or len(record["statement"]) > 16000
                or len(encode(record)) > 24000 or record["project_id"] is None):
            raise AgentError("sourced_bounded_project_record_required")
        self.store.paths.project_workspace(record["project_id"])
        if record["retention_class"] == "temporary" and not record.get("expires_at"):
            raise AgentError("temporary_record_requires_expiry")
        with self.store.transaction():
            Trust(self.store).attest("memory", record["id"], record["project_id"], record,
                                     record["sensitivity"])
            for previous_id in record["supersedes"]:
                previous = self.db.execute("SELECT document FROM memory WHERE id=? AND removed=0",
                                           (previous_id,)).fetchone()
                if not previous:
                    raise AgentError("superseded_record_not_found")
                previous = json.loads(previous[0])
                if (previous["project_id"] != record["project_id"]
                        or previous["sensitivity"] != record["sensitivity"]):
                    raise AgentError("supersession_scope_mismatch")
                if previous["evidence_status"] == "verified" and record["evidence_status"] != "verified":
                    raise AgentError("unverified_supersession_denied")
            self.db.execute("INSERT INTO memory(id,project_id,sensitivity,statement,document)"
                            " VALUES (?,?,?,?,?)", (record["id"], record["project_id"],
                            record["sensitivity"], record["statement"], encode(record)))
            self.db.execute("INSERT INTO memory_fts(id,statement) VALUES (?,?)",
                            (record["id"], record["statement"]))
            self.db.execute("INSERT INTO memory_events VALUES (?,?,?,?)",
                            (uid(), "added", record["id"], now()))
        return record["id"]

    def remember(self, project_id: str, statement: str, source: str, *,
                 sensitivity: str = "private", supersedes: list[str] | None = None,
                 kind: str = "decision", evidence_status: str = "reported") -> str:
        return self.add(dict(id=uid(), project_id=project_id, kind=kind, statement=statement,
                             source_refs=[source], evidence_status=evidence_status,
                             recorded_at=now(), supersedes=supersedes or [],
                             sensitivity=sensitivity, retention_class="durable"))

    def search(self, query: str, *, project_id: str | None, limit: int = 8,
               allowed_classes: tuple[str, ...] = ("public", "internal")) -> list[dict]:
        if not project_id or not 1 <= limit <= 20 or len(query) > 1000:
            raise AgentError("invalid_memory_query")
        # Restricted records are never sent to the M1 model. No wildcard/global query.
        if not allowed_classes or not set(allowed_classes) <= {"public", "internal", "private"}:
            raise AgentError("memory_sensitivity_denied")
        placeholders = ",".join("?" for _ in allowed_classes)
        args = [project_id, *allowed_classes, now()]
        scoped = f"""WITH scoped AS MATERIALIZED (
            SELECT id,document FROM memory WHERE project_id=?
            AND sensitivity IN ({placeholders}) AND removed=0
            AND (json_extract(document,'$.expires_at') IS NULL
                 OR json_extract(document,'$.expires_at') > ?)) """
        # Parse literal words, never accept FTS operators from an untrusted query.
        words = re.findall(r"[^\W_]+", query, re.UNICODE)[:24]
        if query.strip() and not words:
            return []
        condition = ""
        if words:
            condition = " WHERE id IN (SELECT id FROM memory_fts WHERE memory_fts MATCH ?)"
            args.append(" OR ".join('"' + word + '"' for word in words))
        # No global bm25 statistics: sort already-authorized candidates by recorded time.
        rows = self.db.execute(scoped + "SELECT document FROM scoped" + condition +
                               " ORDER BY json_extract(document,'$.recorded_at') DESC LIMIT ?",
                               (*args, limit)).fetchall()
        records = [json.loads(row[0]) for row in rows]
        # Show history links only if the linked record is authorized and still retained.
        for record in records:
            Trust(self.store).require_memory(record, project_id)
            successors = self.db.execute(scoped + "SELECT scoped.id FROM scoped, json_each("
                "json_extract(document,'$.supersedes')) AS s WHERE s.value=?",
                (project_id, *allowed_classes, now(), record["id"])).fetchall()
            record["superseded_by"] = [row[0] for row in successors]
        admit(records)
        return records

    def remove_from_retrieval(self, record_id: str, *, project_id: str):
        """Explicit owner request, auditable soft removal; backup erasure is a later feature."""
        with self.store.transaction():
            result = self.db.execute("UPDATE memory SET removed=1 WHERE id=? AND project_id=?"
                                     " AND removed=0", (record_id, project_id))
            if result.rowcount != 1:
                raise AgentError("record_not_found_in_project")
            self.db.execute("DELETE FROM memory_fts WHERE id=?", (record_id,))
            self.db.execute("INSERT INTO memory_events VALUES (?,?,?,?)",
                            (uid(), "owner_removed_from_retrieval", record_id, now()))

    def _sync_index(self, identifier, project):
        """Caller holds a transaction. Change one derived entry, never canonical data."""
        row = self.db.execute("SELECT document FROM memory WHERE id=? AND project_id=?",
                              (identifier, project)).fetchone()
        if not row:
            return  # A mark in another project cannot alter this record's index.
        self.db.execute("DELETE FROM memory_fts WHERE id=?", (identifier,))
        record = json.loads(row[0])
        try:
            Trust(self.store).require_memory(record, project)
        except AgentError:
            return
        self.db.execute("INSERT INTO memory_fts(id,statement) VALUES (?,?)",
                        (identifier, record["statement"]))

    def rebuild_index(self):
        with self.store.transaction():
            self.db.execute("DELETE FROM memory_fts")
            for row in self.db.execute("SELECT id,project_id FROM memory WHERE removed=0").fetchall():
                self._sync_index(row[0], row[1])
