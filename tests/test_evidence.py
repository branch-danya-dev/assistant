import json

import test_cli
from support import RuntimeCase

from personal_agent.config import AgentError
from personal_agent.demo import run_demo
from personal_agent.storage import encode


class EvidenceTests(RuntimeCase):
    invoke = test_cli.CliTests.invoke

    def completed(self):
        result = run_demo(self.paths)
        self.assertEqual(result["task"]["state"], "completed")
        return result["task"]["task_id"], result["task"]["project_id"], result["actions"][0]["evidence_ref"]

    def test_completion_requires_all_relevant_nonduplicate_refs(self):
        task, action, _ = self.action()
        self.journal.dispatch(action, approval_required=False)
        self.journal.finish(action, {"text": "synthetic"})
        for refs in ([], [f"action:{action}"] * 2, ["action:foreign"], None):
            with self.subTest(refs=refs), self.assertRaises(AgentError):
                self.journal.complete(task, {"evidence_refs": refs})
        self.assertEqual(self.journal.get(task)["state"], "running")

    def test_scoped_saved_evidence_limits_and_secret_withholding(self):
        task, project, ref = self.completed()
        action = self.journal.action(ref.removeprefix("action:"))
        output = json.loads(action["result"])
        output["text"] = "secret=CANARY_SECRET arbitrary sensitive words" * 1000
        self.store.connection.execute("UPDATE actions SET result=? WHERE id=?", (encode(output), action["id"]))
        shown = self.invoke("show-evidence", task, ref, "--project", project)
        self.assertEqual(shown.returncode, 0, shown.stderr)
        data = json.loads(shown.stdout)
        self.assertEqual(data["output"]["sha256"], output["sha256"])
        self.assertNotIn("CANARY_SECRET", shown.stdout)
        self.assertNotIn("arbitrary sensitive words", shown.stdout)
        self.assertLess(len(shown.stdout), 3000)
        limited = self.invoke("show-evidence", task, ref, "--project", project, "--limit", "256")
        self.assertTrue(json.loads(limited.stdout)["truncated"])
        self.assertNotEqual(self.invoke("show-evidence", task, ref, "--project", "foreign").returncode, 0)
        other, _, _ = self.completed()
        self.assertNotEqual(self.invoke("show-evidence", other, ref, "--project", project).returncode, 0)

    def test_memory_evidence_cannot_show_a_foreign_record_even_if_database_result_is_bad(self):
        task, project, _ = self.completed()
        action = self.journal.inspect(task)["actions"][1]
        saved = json.loads(self.journal.action(action["id"])["result"])
        saved["records"][0]["project_id"] = "foreign"
        self.store.connection.execute("UPDATE actions SET result=? WHERE id=?", (encode(saved), action["id"]))
        with self.assertRaisesRegex(AgentError, "evidence_scope_mismatch"):
            self.journal.evidence(task, f"action:{action['id']}", project)
