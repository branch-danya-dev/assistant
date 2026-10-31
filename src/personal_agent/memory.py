"""Canonical sourced records. Authorization filters precede lexical candidate ranking."""
from __future__ import annotations

import json
import re
from contextlib import closing, nullcontext
from datetime import datetime, timezone

from .config import AgentError, validate
from .data_policy import admit
from .storage import Store, encode, now, uid
from .trust import Trust

# Bound full document/receipt validation, including history links. SQL metadata
# filtering does not consume this budget. Exhaustion is explicit, never a silent
# incomplete page. Worker wall-time/output budgets remain independent.
SEARCH_CHECK_LIMIT = 256
RECORD_DENIALS = frozenset({
    "source_review_required", "inventory_source_denied", "memory_sensitivity_denied",
    "invalid_memory-record", "credential_content_denied", "data_nesting_denied",
    "invalid_data_object",
})


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
            self._sync_index(record["id"], record["project_id"])
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
        # Parse literal words, never accept FTS operators from an untrusted query.
        words = re.findall(r"[^\W_]+", query, re.UNICODE)[:24]
        if query.strip() and not words:
            return []
        condition = ""
        query_args = []
        if words:
            condition = " WHERE id IN (SELECT id FROM memory_fts WHERE memory_fts MATCH ?)"
            query_args.append(" OR ".join('"' + word + '"' for word in words))
        # Serialize eligibility checks and derived-index pruning with owner changes.
        # Join an existing owner transaction without committing it.
        with nullcontext() if self.db.in_transaction else self.store.transaction():
            scoped, args = self._scoped(project_id, allowed_classes)
            checked, records = {}, []

            def eligible(row):
                identifier = row["id"]
                if identifier not in checked:
                    if len(checked) >= SEARCH_CHECK_LIMIT:
                        raise AgentError("memory_search_budget_exhausted")
                    checked[identifier] = self._checked_record(row, project_id)
                    if checked[identifier] is None:
                        self.db.execute("DELETE FROM memory_fts WHERE id=?", (identifier,))
                return checked[identifier]

            # No global bm25 statistics. Denied documents cannot consume result
            # slots; a bounded lookahead distinguishes exhaustion from end-of-page.
            order = " ORDER BY json_extract(document,'$.recorded_at') DESC, id ASC LIMIT ?"
            with closing(self.db.execute(scoped + "SELECT id,document FROM scoped" +
                    condition + order, (*args, *query_args, SEARCH_CHECK_LIMIT + 1))) as rows:
                for row in rows:
                    record = eligible(row)
                    if record is not None:
                        records.append(dict(record))
                        if len(records) == limit:
                            break
            # History IDs are a projection too: metadata filters alone do not
            # authorize a tampered successor. Reuse the same full-check budget.
            for record in records:
                links = []
                with closing(self.db.execute(scoped + "SELECT id,document FROM scoped WHERE EXISTS"
                        " (SELECT 1 FROM json_each(json_extract(document,'$.supersedes')) AS s"
                        " WHERE s.value=?)" + order,
                        (*args, record["id"], SEARCH_CHECK_LIMIT + 1))) as rows:
                    for row in rows:
                        if eligible(row) is not None:
                            links.append(row["id"])
                record["superseded_by"] = links
            admit(records)
            return records

    def _scoped(self, project, classes):
        """Cheap current authorization metadata BEFORE ranking/validation limits.

        This is only a candidate filter; _checked_record independently validates
        canonical columns, schema, provenance, digest, receipt and inventory.
        """
        placeholders = ",".join("?" for _ in classes)
        timestamp = now()
        return f"""WITH scoped AS MATERIALIZED (
            SELECT m.id,m.document FROM memory AS m JOIN data_admissions AS a
              ON a.kind='memory' AND a.object_id=m.id AND a.project_id=m.project_id
            WHERE m.project_id=? AND m.sensitivity IN ({placeholders}) AND m.removed=0
              AND a.classification=m.sensitivity AND a.expires_at>?
              AND json_extract(m.document,'$.id')=m.id
              AND json_extract(m.document,'$.project_id')=m.project_id
              AND json_extract(m.document,'$.sensitivity')=m.sensitivity
              AND (json_extract(m.document,'$.expires_at') IS NULL
                   OR json_extract(m.document,'$.expires_at')>?)
              AND NOT EXISTS (SELECT 1 FROM sensitive_inventory AS i
                  WHERE i.kind='memory' AND i.project_id=m.project_id AND i.locator_key=m.id
                    AND (i.reviewed_at IS NULL OR i.expires_at<=?
                         OR i.classification!=m.sensitivity))) """, (
                             project, *classes, timestamp, timestamp, timestamp)

    def _checked_record(self, row, project):
        # Malformed JSON, SQLite errors and unexpected/internal failures propagate.
        # Only enumerated per-source denials are safe to omit from retrieval.
        record = json.loads(row["document"])
        try:
            validate("memory-record", record)
            if record["id"] != row["id"]:
                raise AgentError("source_review_required")
            Trust(self.store).require_memory(record, project)
        except AgentError as exc:
            if str(exc) not in RECORD_DENIALS:
                raise
            return None
        return record

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
        row = self.db.execute("SELECT id,document FROM memory WHERE id=? AND project_id=?",
                              (identifier, project)).fetchone()
        if not row:
            return  # A mark in another project cannot alter this record's index.
        self.db.execute("DELETE FROM memory_fts WHERE id=?", (identifier,))
        record = self._checked_record(row, project)
        if record is None:
            return
        self.db.execute("INSERT INTO memory_fts(id,statement) VALUES (?,?)",
                        (identifier, record["statement"]))

    def rebuild_index(self):
        with self.store.transaction():
            self.db.execute("DELETE FROM memory_fts")
            for row in self.db.execute("SELECT id,project_id FROM memory WHERE removed=0").fetchall():
                self._sync_index(row[0], row[1])
