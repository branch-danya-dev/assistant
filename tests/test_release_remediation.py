"""Independent-audit regressions using synthetic data only."""
import io
import json
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from support import RuntimeCase

from personal_agent import cli
from personal_agent.config import AgentError, specification
from personal_agent.identity import Identity
from personal_agent.orchestrator import Agent
from personal_agent.storage import encode
from personal_agent.trust import Trust


class ApprovalRemediationTests(RuntimeCase):
    def proposal(self):
        workspace = self.paths.project_workspace("alpha")
        workspace.mkdir(exist_ok=True)
        task = self.journal.create("PRIVATE_INTENT_CANARY", "alpha",
            {"files": [], "memory_classes": [], "create_files": ["PRIVATE_NAME_CANARY.txt"],
             "intent_class": "private"})
        self.journal.start(task)
        request = {"task_id": task, "capability_id": "CAP-008", "operation": "create_text",
                   "arguments": {"path": "PRIVATE_NAME_CANARY.txt", "text": "PRIVATE_BODY_CANARY"}}
        self.journal.set_plan(task, [request])
        action = self.journal.prepare(task, 0, request, "workspace_write",
                                      "workspace/alpha/PRIVATE_NAME_CANARY.txt")
        approval = self.journal.request_approval(action)
        return task, action, approval, self.journal.action(action)["digest"]

    def snapshot(self):
        return list(self.store.connection.iterdump())

    def call(self, approval, digest):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(["--root", str(self.paths.root), "approve", approval, "--digest", digest])
        self.assertNotIn("CANARY", out.getvalue() + err.getvalue())
        return code, out.getvalue(), err.getvalue()

    def test_private_ack_then_exact_effect_once(self):
        task, action, approval, digest = self.proposal()
        code, out, err = self.call(approval, digest)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(json.loads(out), {"approval_id": approval, "status": "approved",
            "arguments_digest": digest, "safe_status": "queued"})
        self.assertNotIn("CANARY", encode(self.journal.events(task)))
        Identity(self.paths).initialize()

        class Final:
            def complete(self, messages, *, task_id):
                return {"steps": [], "answer": "Done", "evidence_refs": [f"action:{task_id}:0"]}

        Agent(self.store, Final()).run(task)
        self.assertEqual(self.journal.action(action)["status"], "verified")
        self.assertEqual(self.journal.action(action)["attempts"], 1)
        self.assertEqual(self.journal.approval(approval)["status"], "consumed")
        self.assertEqual((self.paths.project_workspace("alpha") / "PRIVATE_NAME_CANARY.txt")
                         .read_text(), "PRIVATE_BODY_CANARY")
        with self.assertRaises(AgentError):
            self.journal.dispatch(action, approval_required=True)
        self.assertEqual(self.journal.action(action)["attempts"], 1)
        self.assertNotIn("CANARY", encode(self.journal.inspect(task)))

    def test_denial_is_atomic_and_payload_free(self):
        for reason in ("expired", "missing", "foreign", "task_revoked", "file_revoked",
                       "scope_changed", "request_changed", "digest_forged", "resource_changed",
                       "approval_foreign", "grant_readmitted", "action_digest_changed"):
            with self.subTest(reason=reason):
                task, action, approval, digest = self.proposal()
                db, trust = self.store.connection, Trust(self.store)
                if reason == "expired":
                    db.execute("UPDATE data_admissions SET expires_at='2000-01-01T00:00:00Z' WHERE object_id=?", (task,))
                elif reason == "missing":
                    db.execute("DELETE FROM data_admissions WHERE object_id=?", (task,))
                elif reason == "foreign":
                    db.execute("UPDATE data_admissions SET project_id='beta' WHERE object_id=?", (task,))
                elif reason in ("task_revoked", "file_revoked"):
                    trust.mark("task" if reason == "task_revoked" else "file", "alpha",
                               task if reason == "task_revoked" else "PRIVATE_NAME_CANARY.txt")
                elif reason in ("scope_changed", "grant_readmitted"):
                    scope = self.journal.scope(task)
                    scope["create_files"] = []
                    scope["create_bindings"] = {}
                    db.execute("UPDATE tasks SET scope=? WHERE id=?", (encode(scope), task))
                    if reason == "grant_readmitted":
                        trust.refresh_task(task)
                elif reason == "request_changed":
                    req = json.loads(self.journal.action(action)["request"])
                    req["arguments"]["text"] = "CHANGED_CANARY"
                    db.execute("UPDATE actions SET request=? WHERE id=?", (encode(req), action))
                elif reason == "resource_changed":
                    db.execute("UPDATE actions SET resource='CHANGED_CANARY' WHERE id=?", (action,))
                elif reason == "approval_foreign":
                    doc = self.journal.approval(approval)
                    doc["task_id"] = "foreign"
                    db.execute("UPDATE approvals SET document=? WHERE id=?", (encode(doc), approval))
                elif reason == "action_digest_changed":
                    db.execute("UPDATE actions SET digest=? WHERE id=?", ("f" * 64, action))
                else:
                    digest = "0" * 64
                before = self.snapshot()
                self.assertEqual(self.call(approval, digest)[0], 2)
                self.assertEqual(before, self.snapshot())
                self.assertEqual(self.journal.action(action)["attempts"], 0)
                self.assertEqual(self.journal.approval(approval)["status"], "pending")
                self.assertNotIn("CANARY", encode(self.journal.events(task)))
                # Remove the synthetic revocation so the next independent case can be created.
                db.execute("DELETE FROM sensitive_inventory")

    def test_admission_check_is_inside_transaction_and_failure_rolls_back(self):
        _, _, approval, digest = self.proposal()
        original = self.journal.trust.require_task

        def check(*args, **kwargs):
            self.assertTrue(self.store.connection.in_transaction)
            return original(*args, **kwargs)

        before = self.snapshot()
        with patch.object(self.journal.trust, "require_task", side_effect=check), patch.object(
                self.journal, "_transition", side_effect=AgentError("synthetic_failure")):
            with self.assertRaises(AgentError):
                self.journal.approve(approval, digest)
        self.assertEqual(before, self.snapshot())


class AuditOverflowTests(RuntimeCase):
    def seed(self, kind, count, project):
        db = self.store.connection
        for i in range(count):
            identifier = f"{kind}-{i:04}"
            if kind == "task":
                db.execute("INSERT INTO tasks(id,state,document,scope) VALUES (?,?,?,?)",
                    (identifier, "planned", encode({"intent": "BODY_CANARY", "project_id": project}), "{}"))
            elif kind == "memory":
                db.execute("INSERT INTO memory(id,project_id,sensitivity,statement,document) VALUES (?,?,?,?,?)",
                    (identifier, project, "internal", "BODY_CANARY", "{}"))
            elif kind == "preview":
                db.execute("INSERT INTO approval_previews VALUES (?,?,?)", (identifier, "[]", 0))
            elif kind == "persona":
                doc = specification("examples/persona.json")
                doc["version"] = i + 1
                self.paths.file("identity", f"persona-{i+1}.json").write_text(encode(doc), encoding="utf-8")
            else:
                Trust(self.store).mark("file", project, f"LOCATOR_CANARY_{i}.txt")

    def test_every_collection_99_100_101_200_and_global_cap(self):
        for kind in ("task", "memory", "preview", "persona", "inventory"):
            for count in (99, 100, 101, 200):
                with self.subTest(kind=kind, count=count):
                    project = {"preview": "legacy-previews", "persona": "identity"}.get(kind, "alpha")
                    self.seed(kind, count, project)
                    # Source metadata routines themselves are separately exercised by the full suite;
                    # this isolates overflow with every other collection empty.
                    with patch.object(Trust, "review_metadata", side_effect=lambda k, i, p: {"kind": k, "id": i}):
                        result = Trust(self.store).audit(project)
                    self.assertEqual(len(result["items"]) + len(result["inventory"]), min(count, 100))
                    self.assertEqual(result["truncated"], count > 100)
                    self.assertNotIn("CANARY", encode(result))
                    for table in ("tasks", "memory", "approval_previews", "sensitive_inventory"):
                        self.store.connection.execute(f"DELETE FROM {table}")
                    for path in self.paths.directory("identity").glob("persona-*.json"):
                        path.unlink()
        for count in (99, 100, 101, 200):
            for kind in ("task", "memory", "persona", "inventory"):
                self.seed(kind, count, "identity")
            with patch.object(Trust, "review_metadata", side_effect=lambda k, i, p: {"kind": k, "id": i}):
                result = Trust(self.store).audit("identity")
                self.assertEqual(result, Trust(self.store).audit("identity"))
            self.assertEqual(len(result["items"]) + len(result["inventory"]), 300)
            self.assertTrue(result["truncated"])
            self.assertFalse(result["content_disclosed"])
            self.assertEqual(Trust(self.store).audit("foreign")["items"], [])
            for table in ("tasks", "memory", "sensitive_inventory"):
                self.store.connection.execute(f"DELETE FROM {table}")
            for path in self.paths.directory("identity").glob("persona-*.json"):
                path.unlink()
