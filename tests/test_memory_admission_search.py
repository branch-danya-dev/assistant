"""Mixed-admission retrieval through real SQLite FTS5 and the production trust path."""
import io
import json
import sqlite3
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from support import RuntimeCase
from test_data_boundary import BoundaryCase

from personal_agent import cli
from personal_agent.bounded import run_worker
from personal_agent.config import AgentError
from personal_agent.memory import Memory
from personal_agent.orchestrator import Agent
from personal_agent.storage import Store, encode, now
from personal_agent.trust import Trust, fingerprint


class MemoryAdmissionSearchTests(RuntimeCase):
    def setUp(self):
        super().setUp()
        self.db = self.store.connection
        self.memory = Memory(self.store)
        self.trust = Trust(self.store)

    def add(self, identifier, *, project="alpha", sensitivity="internal", **changes):
        record = dict(id=identifier, project_id=project, kind="fact",
                      statement="needle " + identifier, source_refs=["fixture://" + identifier],
                      evidence_status="reported", recorded_at=now(), supersedes=[],
                      sensitivity=sensitivity, retention_class="durable")
        record.update(changes)
        self.memory.add(record)
        return identifier

    def expire(self, identifier):
        self.db.execute("UPDATE data_admissions SET expires_at='2000-01-01T00:00:00Z'"
                        " WHERE kind='memory' AND object_id=?", (identifier,))

    def hits(self, **kwargs):
        return [r["id"] for r in self.memory.search("needle", project_id="alpha", **kwargs)]

    def test_expired_and_valid_in_both_orders(self):
        for first in ("expired", "valid"):
            with self.subTest(first=first):
                self.db.execute("DELETE FROM memory")
                self.db.execute("DELETE FROM memory_fts")
                self.db.execute("DELETE FROM data_admissions")
                self.add(first)
                self.add("valid" if first == "expired" else "expired")
                self.expire("expired")
                self.assertEqual(self.hits(limit=1), ["valid"])
                self.assertEqual(self.hits(), ["valid"])

    def value(self, identifier):
        return json.loads(self.db.execute("SELECT document FROM memory WHERE id=?",
                                         (identifier,)).fetchone()[0])

    def change(self, identifier, **changes):
        value = {**self.value(identifier), **changes}
        self.db.execute("UPDATE memory SET document=? WHERE id=?", (encode(value), identifier))

    def test_missing_expired_and_valid_prefilter_before_full_validation(self):
        self.add("valid")
        self.add("missing")
        self.add("expired")
        self.db.execute("DELETE FROM data_admissions WHERE object_id='missing'")
        self.expire("expired")
        with patch.object(Trust, "require_memory", autospec=True,
                          side_effect=Trust.require_memory) as checked:
            self.assertEqual(self.hits(limit=1), ["valid"])
            self.assertEqual([c.args[1]["id"] for c in checked.call_args_list], ["valid"])
        self.assertEqual([r["id"] for r in self.memory.search("", project_id="alpha")], ["valid"])

    def test_all_source_denials_leave_other_matches_available(self):
        self.add("valid")
        for reason in ("retention", "removed", "deleted", "revoked", "expired_inventory",
                       "inventory_class", "digest", "provenance", "no_provenance",
                       "receipt_project", "receipt_class", "receipt_owner", "receipt_provenance",
                       "column_statement", "document_project", "document_class", "document_id",
                       "invalid_schema"):
            with self.subTest(reason=reason):
                identifier = self.add(reason)
                if reason == "retention":
                    self.change(identifier, expires_at="2000-01-01T00:00:00Z")
                elif reason in ("removed", "deleted"):
                    # Simulate a stale FTS entry as well as canonical removal/deletion.
                    sql = "UPDATE memory SET removed=1 WHERE id=?" if reason == "removed" else "DELETE FROM memory WHERE id=?"
                    self.db.execute(sql, (identifier,))
                elif reason in ("revoked", "expired_inventory", "inventory_class"):
                    mark = self.trust.mark("memory", "alpha", identifier)
                    self.trust.review_mark(mark, "internal")
                    if reason == "revoked":
                        self.db.execute("UPDATE sensitive_inventory SET reviewed_at=NULL WHERE id=?", (mark,))
                    elif reason == "expired_inventory":
                        self.db.execute("UPDATE sensitive_inventory SET expires_at='2000-01-01T00:00:00Z' WHERE id=?", (mark,))
                    else:
                        self.db.execute("UPDATE sensitive_inventory SET classification='private' WHERE id=?", (mark,))
                elif reason.startswith("receipt_"):
                    column, value = {"receipt_project": ("project_id", "beta"),
                        "receipt_class": ("classification", "private"),
                        "receipt_owner": ("owner", "untrusted-model"),
                        "receipt_provenance": ("provenance", "model-claim")}[reason]
                    self.db.execute(f"UPDATE data_admissions SET {column}=? WHERE object_id=?", (value, identifier))
                elif reason == "column_statement":
                    self.db.execute("UPDATE memory SET statement='changed column' WHERE id=?", (identifier,))
                else:
                    changes = {"digest": {"statement": "needle substituted"},
                        "provenance": {"source_refs": ["fixture://substituted"]},
                        "no_provenance": {"source_refs": []},
                        "document_project": {"project_id": "beta"},
                        "document_class": {"sensitivity": "private"},
                        "document_id": {"id": "valid"},
                        "invalid_schema": {"evidence_status": "invented"}}[reason]
                    self.change(identifier, **changes)
                self.assertEqual(self.hits(limit=1), ["valid"])
                self.assertEqual(self.hits(), ["valid"])
        self.memory.rebuild_index()
        self.assertEqual([r[0] for r in self.db.execute("SELECT id FROM memory_fts")], ["valid"])

    def test_metadata_denials_do_not_consume_candidate_or_result_budget(self):
        valid = [self.add(f"valid-{i}") for i in range(3)]
        for i in range(40):
            identifier = self.add(f"denied-{i}")
            if i % 2:
                self.expire(identifier)
            else:
                self.db.execute("DELETE FROM data_admissions WHERE object_id=?", (identifier,))
        with patch("personal_agent.memory.SEARCH_CHECK_LIMIT", 3):
            self.assertEqual(self.hits(limit=3), list(reversed(valid)))

    def test_full_check_denials_refill_limit_and_prune_only_derived_rows(self):
        valid = [self.add(f"valid-{i}") for i in range(3)]
        for i in range(40):
            identifier = self.add(f"tampered-{i}")
            self.change(identifier, source_refs=["fixture://changed"])
        before = [tuple(r) for r in self.db.execute("SELECT * FROM memory")]
        self.assertEqual(self.hits(limit=3), list(reversed(valid)))
        self.assertEqual([tuple(r) for r in self.db.execute("SELECT * FROM memory")], before)
        self.assertEqual(self.db.execute("SELECT count(*) FROM memory_fts").fetchone()[0], 3)

    def test_full_check_budget_is_explicit_and_pruning_rolls_back(self):
        self.add("valid")
        for i in range(256):
            identifier = self.add(f"tampered-{i}")
            self.change(identifier, source_refs=["fixture://changed"])
        with patch.object(Trust, "require_memory", autospec=True,
                          side_effect=Trust.require_memory) as checked:
            with self.assertRaisesRegex(AgentError, "^memory_search_budget_exhausted$"):
                self.hits(limit=1)
            self.assertEqual(checked.call_count, 256)
        self.assertEqual(self.db.execute("SELECT count(*) FROM memory_fts").fetchone()[0], 257)
        self.assertFalse(self.db.in_transaction)

    def test_successor_links_use_full_admission_and_shared_budget(self):
        self.add("original", statement="original")
        self.add("valid", supersedes=["original"])
        self.add("expired", supersedes=["original"])
        self.expire("expired")
        self.add("tampered", supersedes=["original"])
        self.change("tampered", source_refs=["fixture://changed"])
        self.add("private", sensitivity="private", supersedes=[])
        # A malformed cross-class history edge must never disclose a private ID.
        self.change("private", supersedes=["original"])
        result = self.memory.search("original", project_id="alpha")
        self.assertEqual(result[0]["superseded_by"], ["valid"])
        with patch("personal_agent.memory.SEARCH_CHECK_LIMIT", 1):
            with self.assertRaisesRegex(AgentError, "memory_search_budget_exhausted"):
                self.memory.search("original", project_id="alpha")

    def test_private_restricted_foreign_and_cli_diagnostics(self):
        self.add("valid")
        self.add("private", sensitivity="private", statement="needle PRIVATE_CANARY")
        self.add("foreign", project="beta", statement="needle FOREIGN_CANARY")
        self.legacy_restricted_memory("alpha", "needle RESTRICTED_CANARY", "fixture://restricted")
        self.assertEqual(self.hits(), ["valid"])
        self.assertEqual(self.hits(allowed_classes=("private",)), ["private"])
        for private in (False, True):
            out = io.StringIO()
            with redirect_stdout(out):
                code = cli.main(["--root", str(self.paths.root), "memory", "search", "needle",
                                 "--project", "alpha", *(["--include-private"] if private else [])])
            self.assertEqual(code, 0)
            records = json.loads(out.getvalue())["records"]
            self.assertEqual({r["id"] for r in records}, {"valid", "private"} if private else {"valid"})
            for canary in ("PRIVATE_CANARY", "FOREIGN_CANARY", "RESTRICTED_CANARY"):
                self.assertNotIn(canary, out.getvalue())

    def test_owner_review_renewal_and_repeated_revocation(self):
        self.add("valid")
        self.add("expired")
        self.add("legacy")
        self.expire("expired")
        self.db.execute("DELETE FROM data_admissions WHERE object_id='legacy'")
        before = [tuple(r) for r in self.db.execute("SELECT * FROM memory")]
        self.assertEqual(self.hits(), ["valid"])
        self.memory.rebuild_index()
        future = (datetime.now(timezone.utc) + timedelta(days=90)).isoformat()
        self.trust.renew("memory", "expired", "alpha", fingerprint(self.value("expired")),
                         "internal", expires_at=future)
        self.assertEqual(self.hits(), ["expired", "valid"])
        self.trust.review("memory", "legacy", "alpha", fingerprint(self.value("legacy")), "internal")
        self.assertEqual(self.hits(), ["legacy", "expired", "valid"])
        mark = self.trust.mark("memory", "alpha", "expired")
        self.assertEqual(self.hits(), ["legacy", "valid"])
        self.trust.review_mark(mark, "internal")
        self.assertEqual(self.hits(), ["legacy", "expired", "valid"])
        self.trust.review_mark(mark, "restricted")
        self.assertEqual(self.hits(), ["legacy", "valid"])
        self.assertEqual([tuple(r) for r in self.db.execute("SELECT * FROM memory")], before)

    def test_reload_rebuild_and_default_expiry_do_not_renew_receipts(self):
        self.add("valid")
        self.add("expired")
        self.expire("expired")
        receipts = [tuple(r) for r in self.db.execute("SELECT * FROM data_admissions")]
        value = self.db.execute("SELECT expires_at FROM data_admissions WHERE object_id='valid'").fetchone()[0]
        days = (datetime.fromisoformat(value.replace("Z", "+00:00")) - datetime.now(timezone.utc)).total_seconds() / 86400
        self.assertTrue(29.99 < days <= 30)
        for rebuild in (False, True):
            with Store(self.paths) as reopened:
                memory = Memory(reopened)
                if rebuild:
                    memory.rebuild_index()
                self.assertEqual([r["id"] for r in memory.search("needle", project_id="alpha")], ["valid"])
                self.assertEqual(reopened.connection.execute("PRAGMA user_version").fetchone()[0], 4)
        self.assertEqual([tuple(r) for r in self.db.execute("SELECT * FROM data_admissions")], receipts)

    def test_database_and_unknown_internal_failures_abort(self):
        self.add("valid")
        self.db.execute("BEGIN IMMEDIATE")
        self.db.execute("DROP TABLE data_admissions")
        try:
            with self.assertRaises(sqlite3.OperationalError):
                self.hits()
        finally:
            self.db.rollback()
        with patch.object(Trust, "require_memory", side_effect=AgentError("internal_error")):
            with self.assertRaisesRegex(AgentError, "^internal_error$"):
                self.hits()
            with self.assertRaisesRegex(AgentError, "^internal_error$"):
                self.memory.rebuild_index()
        self.assertEqual(self.hits(), ["valid"])
        self.db.execute("UPDATE memory SET document='not-json' WHERE id='valid'")
        with self.assertRaises(sqlite3.OperationalError):
            self.hits()
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(["--root", str(self.paths.root), "memory", "search", "needle", "--project", "alpha"])
        self.assertEqual(code, 2)
        self.assertEqual(out.getvalue(), "")
        self.assertEqual(json.loads(err.getvalue()), {"error": "local_storage_or_permission_error"})

    def test_independent_trust_denies_receipt_label_and_missing_provenance(self):
        self.add("valid")
        self.db.execute("UPDATE data_admissions SET classification='private' WHERE object_id='valid'")
        with self.assertRaisesRegex(AgentError, "memory_sensitivity_denied"):
            self.trust.require_memory(self.value("valid"), "alpha")
        self.change("valid", source_refs=[])
        self.db.execute("UPDATE data_admissions SET classification='internal',digest=? WHERE object_id='valid'",
                        (fingerprint(self.value("valid")),))
        with self.assertRaisesRegex(AgentError, "source_review_required"):
            self.trust.require_memory(self.value("valid"), "alpha")
        self.assertEqual(self.hits(), [])

    def test_literal_fts_query_and_stable_tie_order(self):
        timestamp = now()
        for identifier in ("b", "a"):
            self.add(identifier, recorded_at=timestamp, statement="needle Привет")
        self.add("foreign", project="beta", statement="otherword")
        for query in ('needle OR "otherword"', '"Привет" NEAR (*)', ""):
            self.assertEqual([r["id"] for r in self.memory.search(query, project_id="alpha")], ["a", "b"])
        self.assertEqual(self.memory.search('"*():_', project_id="alpha"), [])


    def test_late_expiry_revocation_or_deletion_is_rechecked_per_candidate(self):
        self.add("valid")
        original = self.memory._checked_record
        for reason in ("expiry", "revocation", "deletion"):
            with self.subTest(reason=reason):
                self.add(reason)

                def change_after_selection(row, project):
                    if row["id"] == reason:
                        if reason == "expiry":
                            self.expire(reason)
                        elif reason == "revocation":
                            self.db.execute("UPDATE data_admissions SET classification='restricted' WHERE object_id=?", (reason,))
                        else:
                            self.db.execute("DELETE FROM memory WHERE id=?", (reason,))
                    return original(row, project)

                # Real policy and SQL; inject the change between selection and checking.
                with patch.object(self.memory, "_checked_record", side_effect=change_after_selection):
                    self.assertEqual(self.hits(limit=1), ["valid"])

    def test_search_joins_owner_transaction_without_committing_it(self):
        self.add("valid")
        self.add("tampered")
        self.change("tampered", source_refs=["fixture://changed"])
        self.db.execute("BEGIN IMMEDIATE")
        self.assertEqual(self.hits(), ["valid"])
        self.assertTrue(self.db.in_transaction)
        self.db.rollback()
        self.assertEqual(self.db.execute("SELECT count(*) FROM memory_fts").fetchone()[0], 2)


class MemorySearchBoundaryTests(BoundaryCase):
    def test_actual_worker_mixed_search_has_no_denied_payload_or_replay(self):
        memory = Memory(self.store)
        valid = memory.remember("alpha", "needle allowed", "fixture://allowed", sensitivity="internal")
        denied = []
        for reason in ("expired", "missing", "tampered", "private", "foreign", "revoked"):
            identifier = memory.remember("beta" if reason == "foreign" else "alpha",
                "needle " + self.canary, "fixture://" + self.canary,
                sensitivity="private" if reason == "private" else "internal")
            denied.append(identifier)
            db = self.store.connection
            if reason == "expired":
                db.execute("UPDATE data_admissions SET expires_at='2000-01-01T00:00:00Z' WHERE object_id=?", (identifier,))
            elif reason == "missing":
                db.execute("DELETE FROM data_admissions WHERE object_id=?", (identifier,))
            elif reason == "tampered":
                db.execute("UPDATE data_admissions SET digest=? WHERE object_id=?", ("0" * 64, identifier))
            elif reason == "revoked":
                Trust(self.store).mark("memory", "alpha", identifier)
        provider = self.reader("search_memory", {"query": "needle"})
        task = self.task()
        captured = []

        def observe_worker(paths, payload, **kwargs):
            captured.append(payload)
            result = run_worker(paths, payload, **kwargs)  # Real child and real SQLite/FTS.
            captured.append(result)
            return result

        out, err = io.StringIO(), io.StringIO()
        with patch("personal_agent.orchestrator.run_worker", side_effect=observe_worker), redirect_stdout(out), redirect_stderr(err):
            result = Agent(self.store, provider).run(task)
        self.assertEqual(result["task"]["state"], "completed")
        action = self.journal.action(task + ":0")
        self.assertEqual([r["id"] for r in json.loads(action["result"])["records"]], [valid])
        self.assertEqual(action["attempts"], 1)
        self.assertEqual(action["effect"], "read")
        with patch("personal_agent.orchestrator.run_worker") as worker:
            with self.assertRaises(AgentError):
                Agent(self.store, provider).run(task, resume=True)
            worker.assert_not_called()
        self.assertEqual(self.journal.action(task + ":0"), action)
        self.assertEqual(self.store.connection.execute("SELECT count(*) FROM approval_previews").fetchone()[0], 0)
        self.assertEqual(self.store.connection.execute("SELECT count(*) FROM approvals").fetchone()[0], 0)
        self.assertEqual(list(self.base.iterdir()), [])
        visible = encode([result, provider.captured, captured, out.getvalue(), err.getvalue(),
                          self.journal.events(task), self.journal.plan(task)])
        self.assertNotIn(self.canary, visible)
        for identifier in denied:
            self.assertNotIn(identifier, visible)
