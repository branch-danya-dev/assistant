"""PR #8 regressions: synthetic data, owner APIs, no live model or credentials."""
import io
import json
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

from support import RuntimeCase

from personal_agent import cli
from personal_agent.config import AgentError
from personal_agent.journal import Journal
from personal_agent.memory import Memory
from personal_agent.orchestrator import Agent
from personal_agent.storage import Store, encode
from personal_agent.trust import Trust, expiry, fingerprint


def future(days=90):
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


class TrustLifecycleTests(RuntimeCase):
    def setUp(self):
        super().setUp()
        self.db = self.store.connection
        self.trust = Trust(self.store)
        self.memory = Memory(self.store)

    def receipt(self, kind, identifier):
        row = self.db.execute("SELECT * FROM data_admissions WHERE kind=? AND object_id=?",
                              (kind, identifier)).fetchone()
        return dict(row) if row else None

    def rows(self, table):
        return [tuple(r) for r in self.db.execute(f"SELECT * FROM {table} ORDER BY rowid")]

    def snapshot(self):
        return {t: self.rows(t) for t in ("tasks", "actions", "approvals", "events",
            "plan_revisions", "data_admissions", "data_reviews", "sensitive_inventory", "memory_fts")}

    def uncertain(self):
        task = self.task()
        self.journal.start(task)
        request = dict(task_id=task, capability_id="CAP-008", operation="create_text",
                       arguments={"path": "new.txt", "text": "synthetic once"})
        self.journal.set_plan(task, [request])
        action = self.journal.prepare(task, 0, request, "workspace_write", "workspace/alpha/new.txt")
        approval = self.journal.request_approval(action)
        self.journal.approve(approval, self.journal.action(action)["digest"])
        self.journal.start(task)
        self.journal.dispatch(action, approval_required=True)
        with self.store.execution_lock():
            self.journal.recover()
        return task, action, approval

    def reconcile(self, task, action, outcome="applied", **kwargs):
        options = {"project": "alpha", "expected_digest":
                   self.trust.review_metadata("task", task, "alpha")["digest"], **kwargs}
        self.journal.reconcile(action, outcome, "fixture://owner-observation", **options)

    def remember(self, project="alpha", sensitivity="internal"):
        return self.memory.remember(project, "needle synthetic payload", "fixture://owner",
                                    sensitivity=sensitivity)

    def expire(self, identifier):
        self.db.execute("UPDATE data_admissions SET expires_at='2000-01-01T00:00:00Z'"
                        " WHERE object_id=?", (identifier,))

    def review(self, identifier, kind="memory", **kwargs):
        meta = self.trust.review_metadata(kind, identifier, "alpha")
        self.trust.review(kind, identifier, "alpha", meta["digest"], meta["classification"], **kwargs)

    def renew(self, identifier, kind="memory", **kwargs):
        meta = self.trust.review_metadata(kind, identifier, "alpha")
        options = {"expires_at": future(), **kwargs}
        self.trust.renew(kind, identifier, "alpha", meta["digest"], meta["classification"], **options)

    def test_reconcile_both_outcomes_refreshes_receipt_without_replay(self):
        for outcome in ("applied", "not_applied"):
            with self.subTest(outcome=outcome):
                task, action, approval = self.uncertain()
                prior = self.receipt("task", task)
                budget = self.journal.get(task)["budget"]
                approved = self.journal.approval(approval)
                events = self.journal.events(task)
                revisions = self.rows("plan_revisions")
                self.reconcile(task, action, outcome)
                shown = self.journal.inspect(task)
                self.assertFalse(shown.get("content_withheld", False))
                self.assertEqual(shown["actions"][0]["reconciliation"]["outcome"], outcome)
                self.assertNotIn("fixture://owner-observation", encode(shown))
                receipt = self.receipt("task", task)
                self.assertEqual(receipt["digest"], fingerprint(self.trust.require_task(task)))
                self.assertNotEqual(receipt["digest"], prior["digest"])
                self.assertEqual(receipt["expires_at"], prior["expires_at"])
                self.assertEqual(self.journal.events(task)[:len(events)], events)
                self.assertEqual(self.rows("plan_revisions"), revisions)
                with patch("personal_agent.orchestrator.run_worker") as worker:
                    with self.assertRaisesRegex(AgentError, "reconciled_action_requires_new_task"):
                        Agent(self.store, Mock()).run(task, resume=True)
                    worker.assert_not_called()
                with self.assertRaisesRegex(AgentError, "action_not_replayable"):
                    self.journal.dispatch(action, approval_required=True)
                self.assertEqual(self.journal.approval(approval), approved)
                self.assertEqual(self.journal.action(action)["attempts"], 1)
                self.assertEqual(self.journal.get(task)["budget"], budget)
                self.assertEqual(len(self.db.execute("SELECT * FROM data_reviews WHERE object_id=?",
                                                     (task,)).fetchall()), 2)

    def test_reconcile_cannot_bootstrap_missing_expired_or_marked_receipts(self):
        for reason in ("missing", "expired", "mark", "restricted", "expired_inventory"):
            with self.subTest(reason=reason):
                task, action, _ = self.uncertain()
                if reason == "missing":
                    self.db.execute("DELETE FROM data_admissions WHERE object_id=?", (task,))
                elif reason == "expired":
                    self.expire(task)
                else:
                    mark = self.trust.mark("task", "alpha", task)
                    if reason == "restricted":
                        self.trust.review_mark(mark, "restricted")
                    elif reason == "expired_inventory":
                        self.trust.review_mark(mark, "internal")
                        self.db.execute("UPDATE sensitive_inventory SET expires_at='2000-01-01T00:00:00Z' WHERE id=?", (mark,))
                before = self.snapshot()
                with self.assertRaises(AgentError):
                    self.reconcile(task, action)
                self.assertEqual(self.snapshot(), before)

    def test_reconcile_rejects_project_digest_and_evidence_substitution(self):
        task, action, _ = self.uncertain()
        before = self.snapshot()
        for options in ({"project": "beta"}, {"expected_digest": "0" * 64}):
            with self.assertRaises(AgentError):
                self.reconcile(task, action, **options)
            self.assertEqual(self.snapshot(), before)
        with self.assertRaisesRegex(AgentError, "reconciliation_evidence_required"):
            self.journal.reconcile(action, "applied", "x" * 1001, project="alpha", expected_digest="0" * 64)
        other_task, other_action, _ = self.uncertain()
        with self.assertRaisesRegex(AgentError, "evidence_scope_mismatch"):
            self.journal.reconcile(action, "applied", "action:" + other_action, project="alpha",
                expected_digest=self.trust.review_metadata("task", task, "alpha")["digest"])
        self.assertEqual(self.journal.get(other_task)["state"], "needs_reconciliation")
        self.reconcile(task, action)
        before = self.snapshot()
        with self.assertRaisesRegex(AgentError, "action_not_uncertain"):
            self.reconcile(task, action, "not_applied")
        self.assertEqual(self.snapshot(), before)

    def test_reconcile_transaction_rolls_back_every_write_on_receipt_failure(self):
        task, action, _ = self.uncertain()
        before = self.snapshot()
        with patch.object(self.journal.trust, "refresh_task", side_effect=AgentError("source_review_required")):
            with self.assertRaises(AgentError):
                self.reconcile(task, action)
        self.assertEqual(self.snapshot(), before)

    def test_reconcile_and_renew_do_not_clear_stop_or_cancellation(self):
        task, action, _ = self.uncertain()
        self.journal.stop()
        self.db.execute("INSERT INTO controls VALUES (?, '1')", (f"cancel:{task}",))
        before = self.rows("controls")
        self.reconcile(task, action)
        self.renew(task, "task")
        self.assertEqual(self.rows("controls"), before)
        with self.assertRaisesRegex(AgentError, "emergency_stop_active"):
            self.journal.start(task, resume=True)
        self.journal.stop(False)
        self.journal.cancel(task)
        self.assertEqual(self.journal.get(task)["state"], "cancelled")
        with self.assertRaises(AgentError):
            self.journal.start(task, resume=True)

    def test_changed_stored_result_denies_projection_reconcile_and_renew(self):
        task, action, _ = self.uncertain()
        self.db.execute("UPDATE actions SET result=? WHERE id=?", (encode({"forged": "unreviewed payload"}), action))
        before = self.snapshot()
        with self.assertRaises(AgentError):
            self.reconcile(task, action)
        with self.assertRaises(AgentError):
            self.renew(task, "task")
        self.assertTrue(self.journal.inspect(task)["content_withheld"])
        self.assertNotIn("unreviewed payload", encode(self.journal.inspect(task)))
        self.assertEqual(self.snapshot(), before)

    def test_inventory_review_restores_only_exact_current_memory(self):
        identifier = self.remember()
        other = self.remember("beta")
        with patch.object(Trust, "require_memory", side_effect=AssertionError("mark read source")):
            mark = self.trust.mark("memory", "alpha", identifier)
        self.assertEqual(self.memory.search("needle", project_id="alpha"), [])
        self.memory.rebuild_index()
        self.trust.review_mark(mark, "internal")
        self.assertEqual([r["id"] for r in self.memory.search("needle", project_id="alpha")], [identifier])
        self.assertEqual([r["id"] for r in self.memory.search("needle", project_id="beta")], [other])
        self.trust.review_mark(mark, "restricted")
        self.assertEqual(self.memory.search("needle", project_id="alpha"), [])
        with self.assertRaises(AgentError):
            self.review(identifier)

    def test_mark_review_never_resurrects_expired_unreviewed_changed_or_removed(self):
        for reason in ("expired", "missing", "changed", "removed", "retention"):
            identifier = self.remember()
            mark = self.trust.mark("memory", "alpha", identifier)
            if reason == "expired":
                self.expire(identifier)
            elif reason == "missing":
                self.db.execute("DELETE FROM data_admissions WHERE object_id=?", (identifier,))
            elif reason == "changed":
                value, _ = self.trust.review_value("memory", identifier, "alpha")
                value["source_refs"] = ["fixture://changed"]
                self.db.execute("UPDATE memory SET document=? WHERE id=?", (encode(value), identifier))
            elif reason == "removed":
                self.memory.remove_from_retrieval(identifier, project_id="alpha")
            else:
                value, _ = self.trust.review_value("memory", identifier, "alpha")
                value["expires_at"] = "2000-01-01T00:00:00Z"
                self.db.execute("UPDATE memory SET document=? WHERE id=?", (encode(value), identifier))
            self.trust.review_mark(mark, "internal")
            self.memory.rebuild_index()
            self.assertIsNone(self.db.execute("SELECT id FROM memory_fts WHERE id=?", (identifier,)).fetchone())

    def test_data_review_restores_legacy_memory_atomically_and_reboot_rebuild(self):
        identifier = self.remember()
        self.db.execute("DELETE FROM data_admissions WHERE object_id=?", (identifier,))
        self.memory.rebuild_index()
        before = self.snapshot()
        with patch.object(Memory, "_sync_index", side_effect=AgentError("source_review_required")):
            with self.assertRaises(AgentError):
                self.review(identifier)
        self.assertEqual(self.snapshot(), before)
        self.review(identifier)
        self.assertEqual(self.memory.search("needle", project_id="alpha")[0]["id"], identifier)
        with Store(self.paths) as reopened:
            Memory(reopened).rebuild_index()
            self.assertEqual(Memory(reopened).search("needle", project_id="alpha")[0]["id"], identifier)

    def test_private_review_and_wrong_project_marks_do_not_leak_or_change_scope(self):
        identifier = self.remember(sensitivity="private")
        before = self.rows("memory_fts")
        wrong = self.trust.mark("memory", "beta", identifier)
        self.trust.review_mark(wrong, "internal")
        self.assertEqual(self.rows("memory_fts"), before)
        mark = self.trust.mark("memory", "alpha", identifier)
        self.trust.review_mark(mark, "internal")
        self.assertEqual(self.memory.search("needle", project_id="alpha", allowed_classes=("private",)), [])
        self.trust.review_mark(mark, "private")
        self.assertEqual(self.memory.search("needle", project_id="alpha"), [])
        self.assertEqual(self.memory.search("needle", project_id="beta", allowed_classes=("private",)), [])
        self.assertEqual(self.memory.search("needle", project_id="alpha", allowed_classes=("private",))[0]["id"], identifier)

    def test_review_stale_digest_or_changed_columns_fails_closed(self):
        identifier = self.remember()
        meta = self.trust.review_metadata("memory", identifier, "alpha")
        value, _ = self.trust.review_value("memory", identifier, "alpha")
        value["source_refs"] = ["fixture://changed"]
        self.db.execute("UPDATE memory SET document=? WHERE id=?", (encode(value), identifier))
        with self.assertRaisesRegex(AgentError, "review_digest_or_label_mismatch"):
            self.trust.review("memory", identifier, "alpha", meta["digest"], "internal")
        with self.assertRaises(AgentError):
            self.renew(identifier)
        self.db.execute("UPDATE memory SET statement='changed column' WHERE id=?", (identifier,))
        self.memory.rebuild_index()
        self.assertEqual(self.rows("memory_fts"), [])
        with self.assertRaises(AgentError):
            self.review(identifier)

    def test_renew_expired_memory_restores_search_preserves_canonical_history(self):
        identifier = self.remember()
        self.expire(identifier)
        before = {t: self.rows(t) for t in ("memory", "memory_events", "approvals", "events")}
        old = self.receipt("memory", identifier)
        self.assertEqual(self.memory.search("needle", project_id="alpha"), [])
        self.memory.rebuild_index()
        self.renew(identifier)
        self.assertEqual(self.memory.search("needle", project_id="alpha")[0]["id"], identifier)
        self.assertEqual(before, {t: self.rows(t) for t in before})
        history = self.rows("data_reviews")
        self.assertIn(old["expires_at"], history[0])
        self.renew(identifier, expires_at=future(120))
        self.assertEqual(self.rows("data_reviews")[:len(history)], history)
        self.assertEqual(self.receipt("memory", identifier)["digest"], old["digest"])

    def test_renew_denies_revoked_expired_inventory_labels_project_and_expiry(self):
        identifier = self.remember()
        meta = self.trust.review_metadata("memory", identifier, "alpha")
        for project, digest, label, date in (("beta", meta["digest"], "internal", future()),
                ("alpha", "0" * 64, "internal", future()),
                ("alpha", meta["digest"], "public", future()),
                ("alpha", meta["digest"], "internal", "2000-01-01T00:00:00Z"),
                ("alpha", meta["digest"], "internal", None)):
            before = self.snapshot()
            with self.assertRaises(AgentError):
                self.trust.renew("memory", identifier, project, digest, label, expires_at=date)
            self.assertEqual(self.snapshot(), before)
        mark = self.trust.mark("memory", "alpha", identifier)
        for state in ("marked", "expired"):
            if state == "expired":
                self.trust.review_mark(mark, "internal")
                self.db.execute("UPDATE sensitive_inventory SET expires_at='2000-01-01T00:00:00Z' WHERE id=?", (mark,))
            before = self.snapshot()
            with self.assertRaises(AgentError):
                self.renew(identifier)
            self.assertEqual(self.snapshot(), before)

    def test_expired_task_audit_renewal_keeps_consumption_state_and_history(self):
        task, action, approval = self.uncertain()
        self.reconcile(task, action)
        self.expire(task)
        before = {t: self.rows(t) for t in ("tasks", "actions", "approvals", "events", "plan_revisions")}
        audit = self.journal.historical_audit(task, "alpha")
        self.assertEqual(audit["actions"][0]["approval_status"], "consumed")
        self.assertEqual(audit["admission"]["review"], "required")
        for payload in ("synthetic once", "fixture://owner-observation", "new.txt", "Synthetic test"):
            self.assertNotIn(payload, encode(audit))
        with self.assertRaises(AgentError):
            self.journal.historical_audit(task, "beta")
        self.renew(task, "task")
        self.assertEqual(self.trust.review_metadata("task", task, "alpha")["review"], "current")
        self.assertEqual(before, {t: self.rows(t) for t in before})
        with Store(self.paths) as reopened:
            with self.assertRaises(AgentError):
                Journal(reopened).start(task, resume=True)
        self.assertEqual(self.journal.approval(approval)["status"], "consumed")

    def test_default_thirty_days_and_explicit_owner_cli_renewal(self):
        days = (datetime.fromisoformat(expiry().replace("Z", "+00:00")) - datetime.now(timezone.utc)).total_seconds() / 86400
        self.assertAlmostEqual(days, 30, places=4)
        identifier = self.remember()
        self.expire(identifier)
        meta = self.trust.review_metadata("memory", identifier, "alpha")
        out = io.StringIO()
        with redirect_stdout(out):
            result = cli.main(["--root", str(self.paths.root), "data-renew", "memory", identifier,
                "--project", "alpha", "--digest", meta["digest"], "--classification", "internal",
                "--expires-at", future()])
        self.assertEqual(result, 0)
        self.assertFalse(json.loads(out.getvalue())["effect_approval_granted"])
        self.assertEqual(self.memory.search("needle", project_id="alpha")[0]["id"], identifier)

    def test_owner_review_then_reconcile_and_cli_audit_require_project(self):
        task, action, _ = self.uncertain()
        self.db.execute("DELETE FROM data_admissions WHERE object_id=?", (task,))
        with self.assertRaises(AgentError):
            self.reconcile(task, action)
        self.review(task, "task")
        meta = self.trust.review_metadata("task", task, "alpha")
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(cli.main(["--root", str(self.paths.root), "reconcile", action,
                "--outcome", "not_applied", "--evidence", "fixture://owner-checked",
                "--project", "alpha", "--digest", meta["digest"]]), 0)
        self.expire(task)
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(cli.main(["--root", str(self.paths.root), "show-audit", task,
                                      "--project", "alpha"]), 2)  # Existing blocked-task CLI status.
        self.assertEqual(json.loads(output.getvalue())["actions"][0]["status"], "reconciled")
        self.assertNotIn("fixture://owner-checked", output.getvalue())

    def test_review_and_renew_cannot_restore_expired_retention_or_removed_memory(self):
        for reason in ("retention", "removed", "restricted"):
            identifier = self.remember()
            if reason == "removed":
                self.memory.remove_from_retrieval(identifier, project_id="alpha")
            else:
                value, _ = self.trust.review_value("memory", identifier, "alpha")
                if reason == "retention":
                    value["expires_at"] = "2000-01-01T00:00:00Z"
                else:
                    value["sensitivity"] = "restricted"
                    self.db.execute("UPDATE memory SET sensitivity='restricted' WHERE id=?", (identifier,))
                self.db.execute("UPDATE memory SET document=? WHERE id=?", (encode(value), identifier))
            self.memory.rebuild_index()
            before = self.snapshot()
            for operation in (self.review, self.renew):
                with self.assertRaises(AgentError):
                    operation(identifier)
                self.assertEqual(self.snapshot(), before)

    def test_file_inventory_blocks_reconcile_and_renew_without_rewriting_scope(self):
        task, action, _ = self.uncertain()
        # Owner scope created before dispatch; use a second task with an actual file grant.
        scoped = self.task(files=["source.txt"])
        self.trust.mark("file", "alpha", "source.txt")
        before = self.snapshot()
        with self.assertRaises(AgentError):
            self.renew(scoped, "task")
        self.assertEqual(self.snapshot(), before)
        # A task inventory gate also refuses the uncertain transition without changing effects.
        self.trust.mark("task", "alpha", task)
        before = self.snapshot()
        with self.assertRaises(AgentError):
            self.reconcile(task, action)
        self.assertEqual(self.snapshot(), before)
