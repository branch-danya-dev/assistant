"""Owner-only metadata inventory and admission receipts; never a credential store.

The local owner/code/database are trusted. No model/tool exposes these mutations.
Receipts bind saved content, but do not discover opaque secrets in misclassified data.
"""
from __future__ import annotations

import hashlib
import json
import unicodedata
from datetime import datetime, timedelta, timezone

from .config import AgentError, safe_relative, validate
from .data_policy import CLASSES, admit, file_access, validate_scope
from .storage import encode, now, uid

LOCAL_SINKS = frozenset({"journal", "worker", "ollama", "preview"})
KINDS = frozenset({"task", "memory", "persona", "preview"})


def inventory_key(path):
    # Persist a platform-independent conservative denial key. Moving the database
    # between Windows/Linux must never make a known source lose its mark. This is
    # not a filename resolver/grant and may deny distinct Linux/Unicode spellings.
    return unicodedata.normalize("NFC", path.casefold())


def fingerprint(value):
    return hashlib.sha256(encode(value).encode("utf-8")).hexdigest()


def expiry(value=None):
    try:
        date = (datetime.fromisoformat(value.replace("Z", "+00:00")) if value else
                datetime.now(timezone.utc) + timedelta(days=30))
        if date.tzinfo is None or not datetime.now(timezone.utc) < date <= (
                datetime.now(timezone.utc) + timedelta(days=366)):
            raise ValueError
        return date.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    except (ValueError, TypeError, AttributeError):
        raise AgentError("invalid_review_expiry") from None


class Trust:
    def __init__(self, store):
        self.store, self.db = store, store.connection

    def guard(self, kind, project, locator):
        if kind not in KINDS | {"file"}:
            raise AgentError("unclassified_source_denied")
        key = inventory_key(locator) if kind == "file" else locator
        row = self.db.execute("SELECT * FROM sensitive_inventory WHERE kind=? AND project_id=?"
                              " AND locator_key=?", (kind, project, key)).fetchone()
        if row and (not row["reviewed_at"] or row["expires_at"] <= now()
                    or row["classification"] not in CLASSES - {"restricted"}):
            raise AgentError("inventory_source_denied")
        return row["classification"] if row else None

    def mark(self, kind, project, locator, classification="restricted", *, expires_at=None):
        """Metadata supplied by owner, no discovery, crawling or credential reads."""
        if kind not in KINDS | {"file"} or classification not in CLASSES | {"unclassified"}:
            raise AgentError("invalid_inventory_metadata")
        self.store.paths.project_workspace(project)
        if kind == "file":
            if safe_relative(locator) != locator:
                raise AgentError("invalid_inventory_metadata")
        if not isinstance(locator, str) or not 1 <= len(locator) <= 1000:
            raise AgentError("invalid_inventory_metadata")
        admit(locator)
        key = inventory_key(locator) if kind == "file" else locator
        identifier, timestamp = uid(), expiry(expires_at)
        with self.store.transaction():
            self.db.execute("INSERT INTO sensitive_inventory VALUES (?,?,?,?,?,?,?,?,?,?)",
                (identifier, kind, project, locator, key, classification, "local-owner",
                 "owner-mark", None, timestamp))
            if kind == "memory":
                # Revocation is metadata-only; never parse the source to suppress its index.
                self.db.execute("DELETE FROM memory_fts WHERE id=? AND EXISTS"
                    " (SELECT 1 FROM memory WHERE id=? AND project_id=?)", (locator, locator, project))
        return identifier

    def review_mark(self, identifier, classification, *, expires_at=None):
        if classification not in CLASSES:
            raise AgentError("invalid_inventory_metadata")
        timestamp = expiry(expires_at)
        with self.store.transaction():
            row = self.db.execute("SELECT * FROM sensitive_inventory WHERE id=?", (identifier,)).fetchone()
            if not row:
                raise AgentError("inventory_entry_not_found")
            self.db.execute("UPDATE sensitive_inventory SET classification=?, reviewed_at=?,"
                            " expires_at=?,provenance='owner-review' WHERE id=?",
                            (classification, now(), timestamp, identifier))
            self.db.execute("INSERT INTO data_reviews VALUES (?,?,?,?,?,?,?)",
                (uid(), "inventory", identifier, fingerprint(dict(row)), classification, now(), timestamp))
            self._sync_memory(row["kind"], row["locator"], row["project_id"])

    def _sync_memory(self, kind, identifier, project):
        if kind == "memory":
            from .memory import Memory
            Memory(self.store)._sync_index(identifier, project)

    def attest(self, kind, object_id, project, value, classification, *,
               provenance="owner-create", expires_at=None):
        if kind not in KINDS or classification not in CLASSES - {"restricted"}:
            raise AgentError("unclassified_source_denied")
        marked = self.guard(kind, project, object_id)
        if marked == "private" and classification != "private":
            raise AgentError("inventory_source_denied")
        admit(value)
        self.db.execute("INSERT OR REPLACE INTO data_admissions VALUES (?,?,?,?,?,?,?,?,?)",
            (kind, object_id, project, fingerprint(value), classification, "local-owner",
             provenance, now(), expiry(expires_at)))

    def require(self, kind, object_id, project, value, *, sink="journal"):
        if sink not in LOCAL_SINKS | {"diagnostics"}:
            raise AgentError("unclassified_sink_denied")
        marked = self.guard(kind, project, object_id)
        row = self.db.execute("SELECT * FROM data_admissions WHERE kind=? AND object_id=?",
                              (kind, object_id)).fetchone()
        if (not row or row["project_id"] != project or row["expires_at"] <= now()
                or row["digest"] != fingerprint(value)
                or row["owner"] != "local-owner" or not row["reviewed_at"]
                or row["provenance"] not in {"owner-create", "legacy-owner-review",
                                              "owner-renewal", "admitted-derivation"}
                or row["classification"] not in CLASSES - {"restricted"}):
            raise AgentError("source_review_required")
        if marked == "private" and row["classification"] != "private":
            raise AgentError("inventory_source_denied")
        if sink == "diagnostics" and row["classification"] == "private":
            raise AgentError("private_sink_denied")
        admit(value)
        return row["classification"]

    def task_value(self, identifier):
        row = self.db.execute("SELECT * FROM tasks WHERE id=?", (identifier,)).fetchone()
        if not row:
            raise AgentError("task_not_found")
        task = json.loads(row["document"])
        # Mutable lifecycle counters/statuses are deliberately excluded. Every source,
        # saved plan/revision/result is included. Review cannot modify authority/effects.
        return {"intent": task["intent"], "project": task["project_id"],
                "scope": json.loads(row["scope"]), "plan": json.loads(row["plan"]),
                "result": json.loads(row["result"]) if row["result"] else None,
                "revisions": [r[0] for r in self.db.execute(
                    "SELECT document FROM plan_revisions WHERE task_id=? ORDER BY revision", (identifier,))],
                "actions": [dict(r) for r in self.db.execute(
                    "SELECT id,request,result FROM actions WHERE task_id=? ORDER BY ordinal", (identifier,))]}

    def task_class(self, value):
        scope = value["scope"]
        return "private" if (scope.get("intent_class") == "private" or scope.get("private_files") or
                            "private" in scope.get("memory_classes", [])) else "internal"

    def refresh_task(self, identifier, *, new=False):
        value = self.task_value(identifier)
        prior = self.db.execute("SELECT expires_at FROM data_admissions WHERE kind='task'"
                                " AND object_id=?", (identifier,)).fetchone()
        if not prior and not new:
            raise AgentError("source_review_required")
        self.attest("task", identifier, value["project"], value, self.task_class(value),
                    provenance="owner-create" if new else "admitted-derivation",
                    expires_at=prior[0] if prior else None)

    def check_scope(self, project, scope, *, sink):
        validate_scope(scope)
        for path in scope.get("files", []) + scope.get("create_files", []):
            marked = self.guard("file", project, path)
            if marked == "private" and path not in scope.get("private_files", []):
                raise AgentError("inventory_source_denied")
        for path in scope.get("files", []):
            file_access(path, scope)
        private = (scope.get("intent_class") == "private" or scope.get("private_files") or
                   "private" in scope.get("memory_classes", []))
        if private and (sink not in scope.get("local_sinks", []) or
                        scope.get("local_purpose") != "owner-task"):
            raise AgentError("private_sink_denied")

    def require_task(self, identifier, *, sink="journal"):
        value = self.task_value(identifier)
        # Alias errors remain precise; never normalize stored scope on review/resume.
        validate_scope(value["scope"])
        self.require("task", identifier, value["project"], value, sink=sink)
        self.check_scope(value["project"], value["scope"], sink=sink)
        for action in value["actions"]:
            if action["result"]:
                result = json.loads(action["result"])
                request = json.loads(action["request"])
                if request["operation"] == "search_memory":
                    for record in result.get("records", []):
                        self.require_memory(record, value["project"], sink=sink)
        return value

    def require_memory(self, record, project, *, sink="journal"):
        canonical = {k: v for k, v in record.items() if k != "superseded_by"}
        if record.get("project_id") != project or record.get("sensitivity") == "restricted":
            raise AgentError("memory_sensitivity_denied")
        current, _ = self.review_value("memory", record["id"], project)
        row = self.db.execute("SELECT removed FROM memory WHERE id=?", (record["id"],)).fetchone()
        if (canonical != current or not row or row[0] or not current.get("source_refs") or
                (current.get("expires_at") and current["expires_at"] <= now())):
            raise AgentError("source_review_required")
        marked = self.guard("memory", project, record["id"])
        if marked and marked != record["sensitivity"]:
            raise AgentError("inventory_source_denied")
        classification = self.require("memory", record["id"], project, canonical, sink=sink)
        if classification != record.get("sensitivity"):
            raise AgentError("memory_sensitivity_denied")
        return classification

    def audit(self, project):
        """Bounded IDs/labels/digests only: no source bodies, paths or preview reads."""
        self.store.paths.project_workspace(project)
        result, truncated = [], False
        for kind, query in (("task", "SELECT id FROM tasks WHERE json_extract(document,'$.project_id')=?"),
                            ("memory", "SELECT id FROM memory WHERE project_id=?")):
            rows = self.db.execute(query + " ORDER BY id LIMIT 101", (project,)).fetchall()
            truncated |= len(rows) > 100
            for row in rows[:100]:
                result.append(self.review_metadata(kind, row[0], project))
        # Previews have no project binding in v3: global IDs only, never open their files.
        if project == "legacy-previews":
            rows = self.db.execute("SELECT name,expires FROM approval_previews ORDER BY name LIMIT 101").fetchall()
            truncated |= len(rows) > 100
            for row in rows[:100]:
                result.append({"kind": "preview", "id": row[0], "review": "metadata-only-no-admission",
                               "expires_at_unix": row[1]})
        if project == "identity":
            from .identity import Identity
            for version in Identity(self.store.paths).versions()[:100]:
                result.append(self.review_metadata("persona", str(version), project))
        return {"items": result[:300], "limit": 100, "truncated": truncated or len(result) > 300,
                "inventory": [{k: r[k] for k in ("id", "kind", "classification", "owner",
                    "provenance", "reviewed_at", "expires_at")} for r in self.db.execute(
                    "SELECT * FROM sensitive_inventory WHERE project_id=? ORDER BY id LIMIT 100", (project,))],
                "content_disclosed": False, "unregistered_previews_scanned": False}

    def review_value(self, kind, identifier, project):
        if kind == "persona" and project == "identity" and identifier.isdigit():
            from .config import reject_links
            path = self.store.paths.file("identity", f"persona-{int(identifier)}.json")
            reject_links(path)
            if path.stat().st_size > 12000:
                raise AgentError("persona_size_exceeded")
            value = json.loads(path.read_text(encoding="utf-8"))
            validate("persona", value)
            return value, "internal"
        if kind == "task":
            value = self.task_value(identifier)
            if value["project"] != project:
                raise AgentError("task_scope_mismatch")
            return value, self.task_class(value)
        if kind == "memory":
            row = self.db.execute("SELECT * FROM memory WHERE id=? AND project_id=?",
                                  (identifier, project)).fetchone()
            if row:
                value = json.loads(row["document"])
                validate("memory-record", value)
                if any(value[key] != row[column] for key, column in (
                        ("id", "id"), ("project_id", "project_id"),
                        ("sensitivity", "sensitivity"), ("statement", "statement"))):
                    raise AgentError("source_review_required")
                return value, value["sensitivity"]
        raise AgentError("source_review_required")

    def review_metadata(self, kind, identifier, project):
        value, classification = self.review_value(kind, identifier, project)
        row = self.db.execute("SELECT digest,expires_at FROM data_admissions WHERE kind=? AND object_id=?",
                              (kind, identifier)).fetchone()
        digest = fingerprint(value)
        try:
            if kind == "task":
                self.require_task(identifier)
            elif kind == "memory":
                self.require_memory(value, project)
            else:
                self.require(kind, identifier, project, value)
            status = "current"
        except AgentError:
            status = "required"
        return {"kind": kind, "id": identifier, "digest": digest, "classification": classification,
                "review": status, "admitted_digest": row[0] if row else None,
                "expires_at": row[1] if row else None}

    def _archive_admission(self, kind, identifier):
        row = self.db.execute("SELECT * FROM data_admissions WHERE kind=? AND object_id=?",
                              (kind, identifier)).fetchone()
        if row:
            self.db.execute("INSERT INTO data_reviews VALUES (?,?,?,?,?,?,?)",
                (uid(), kind, identifier, row["digest"], row["classification"],
                 row["reviewed_at"], row["expires_at"]))

    def _reviewed_admission(self, kind, identifier, project, value, classification, timestamp,
                            provenance):
        self._archive_admission(kind, identifier)
        self.attest(kind, identifier, project, value, classification,
                    provenance=provenance, expires_at=timestamp)
        if kind == "memory":
            self.require_memory(value, project)
            self._sync_memory(kind, identifier, project)
        self.db.execute("INSERT INTO data_reviews VALUES (?,?,?,?,?,?,?)",
            (uid(), kind, identifier, fingerprint(value), classification, now(), timestamp))

    def renew(self, kind, identifier, project, digest, classification, *, expires_at):
        """Owner-only renewal of unchanged reviewed bytes; never restores effect authority."""
        if not expires_at:
            raise AgentError("invalid_review_expiry")
        timestamp = expiry(expires_at)
        with self.store.transaction():
            value, existing = self.review_value(kind, identifier, project)
            prior = self.db.execute("SELECT * FROM data_admissions WHERE kind=? AND object_id=?",
                                    (kind, identifier)).fetchone()
            if (not prior or prior["project_id"] != project or prior["digest"] != digest
                    or fingerprint(value) != digest or classification != existing
                    or prior["classification"] != classification):
                raise AgentError("review_digest_or_label_mismatch")
            if timestamp <= prior["expires_at"]:
                raise AgentError("invalid_review_expiry")
            self._reviewed_admission(kind, identifier, project, value, classification,
                                     timestamp, "owner-renewal")
            if kind == "task":
                self.require_task(identifier)  # Current scope, inventory and saved memory too.

    def review(self, kind, identifier, project, digest, classification, *, expires_at=None):
        """Owner attests independently reviewed bytes by ID/hash; never changes source rows.

        Missing file labels and ambiguous grants still block after review: create a new task.
        A content review is not an effect approval and cannot replay completed actions.
        """
        with self.store.transaction():
            value, existing = self.review_value(kind, identifier, project)
            if fingerprint(value) != digest or classification != existing:
                raise AgentError("review_digest_or_label_mismatch")
            self._reviewed_admission(kind, identifier, project, value, classification,
                                     expiry(expires_at), "legacy-owner-review")
