import json
import os
import subprocess
import sys

from support import REPO, RuntimeCase

from personal_agent.config import AgentError, validate
from personal_agent.journal import Journal
from personal_agent.storage import Store, encode


class JournalTests(RuntimeCase):
    def test_schema_and_durable_events(self):
        task, action, _ = self.action()
        self.journal.dispatch(action, approval_required=False)
        self.journal.finish(action, {"text": "synthetic"})
        self.journal.complete(task, {"answer": "read verified", "evidence_refs": [f"action:{action}"]})
        with Store(self.paths) as reopened:
            journal = Journal(reopened)
            validate("task-state", journal.get(task))
            events = journal.events(task)
            self.assertEqual([x["sequence"] for x in events], list(range(1, len(events) + 1)))
            for event in events:
                validate("task-event", event)
            self.assertEqual(journal.get(task)["state"], "completed")
            with self.assertRaises(AgentError):
                journal.start(task, resume=True)

    def test_approval_exact_once(self):
        task, action, request = self.action("external_send")
        approval = self.journal.request_approval(action)
        fingerprint = self.journal.action(action)["digest"]
        with self.assertRaises(AgentError):
            self.journal.approve(approval, "wrong")
        self.journal.approve(approval, fingerprint)
        self.journal.start(task)
        with self.assertRaises(AgentError):
            self.journal.prepare(task, 0, {**request, "arguments": {"path": "changed"}},
                                 "external_send", "workspace/alpha/fixture.txt")
        self.journal.dispatch(action, approval_required=False)
        self.assertEqual(self.journal.approval(approval)["status"], "consumed")
        with self.assertRaises(AgentError):
            self.journal.dispatch(action, approval_required=False)

    def test_expired_approval_cannot_dispatch(self):
        task, action, _ = self.action("external_send")
        approval_id = self.journal.request_approval(action)
        self.journal.approve(approval_id, self.journal.action(action)["digest"])
        approval = self.journal.approval(approval_id)
        approval["expires_at"] = "2000-01-01T00:00:00Z"
        self.store.connection.execute("UPDATE approvals SET document=? WHERE id=?",
                                      (encode(approval), approval_id))
        self.journal.start(task)
        with self.assertRaises(AgentError):
            self.journal.dispatch(action, approval_required=True)
        self.assertEqual(self.journal.action(action)["status"], "pending")

    def test_crash_after_effect(self):
        """SCN-010: real child exits abruptly after synthetic effect, before acknowledgment."""
        task, action, _ = self.action("external_send")
        approval = self.journal.request_approval(action)
        self.journal.approve(approval, self.journal.action(action)["digest"])
        self.journal.start(task)
        script = """
import os, sys
from pathlib import Path
from personal_agent.config import Paths
from personal_agent.storage import Store
from personal_agent.journal import Journal
with Store(Paths(sys.argv[1])) as store, store.execution_lock():
    Journal(store).dispatch(sys.argv[2], approval_required=True)
    Path(sys.argv[1], 'workspace', 'effect.txt').write_text('once')
    os._exit(17)
"""
        result = subprocess.run([sys.executable, "-c", script, str(self.paths.root), action],
                                env={**os.environ, "PYTHONPATH": str(REPO / "src")}, timeout=20)
        self.assertEqual(result.returncode, 17)
        with self.store.execution_lock():
            self.journal.recover()
            self.assertEqual(self.journal.get(task)["state"], "needs_reconciliation")
            with self.assertRaises(AgentError):
                self.journal.start(task, resume=True)
            with self.assertRaises(AgentError):
                self.journal.dispatch(action, approval_required=True)
        self.assertEqual(self.paths.under("workspace/effect.txt").read_text(), "once")
        self.assertEqual(self.journal.approval(approval)["status"], "consumed")
        self.journal.reconcile(action, "applied", "fixture://observed-effect")
        self.assertEqual(self.journal.get(task)["state"], "blocked")
        with self.assertRaises(AgentError):
            self.journal.dispatch(action, approval_required=True)

    def test_before_dispatch_and_after_acknowledgment_recovery(self):
        task, action, _ = self.action()
        with self.store.execution_lock():
            self.journal.recover()
        self.assertEqual(self.journal.action(action)["status"], "pending")
        self.journal.start(task, resume=True)
        self.journal.dispatch(action, approval_required=False)
        self.journal.finish(action, {"text": "done"})
        with self.store.execution_lock():
            self.journal.recover()
        self.assertEqual(self.journal.action(action)["status"], "verified")
        self.journal.start(task, resume=True)
        with self.assertRaises(AgentError):
            self.journal.dispatch(action, approval_required=False)

    def test_stop_is_persistent_and_denies_new_dispatch(self):
        task, action, _ = self.action()
        self.journal.stop()
        with self.assertRaises(AgentError):
            self.journal.dispatch(action, approval_required=False)
        with Store(self.paths) as reopened:
            self.assertTrue(Journal(reopened).stopped())
        self.assertEqual(self.journal.action(action)["status"], "pending")

    def test_fabricated_evidence_and_budget(self):
        task = self.task(budget={"model_limit": 1})
        self.journal.start(task)
        self.journal.model_call(task)
        with self.assertRaises(AgentError):
            self.journal.model_call(task)
        with self.assertRaises(AgentError):
            self.journal.complete(task, {"evidence_refs": ["fake"]})
        self.assertNotIn("Synthetic", json.dumps(self.journal.events(task)))
