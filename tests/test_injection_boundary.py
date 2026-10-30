"""Do not rely on a model recognizing injection: simulate a fully persuaded model."""
import json
from pathlib import Path

from test_data_boundary import BoundaryCase

from personal_agent.memory import Memory
from personal_agent.orchestrator import Agent
from personal_agent.storage import encode


class InjectionTests(BoundaryCase):
    def test_supported_operations_after_real_hostile_file_and_memory_results(self):
        payloads = json.loads((Path(__file__).parent / "fixtures/injection.json").read_text(encoding="utf-8"))
        for source in ("file", "memory"):
            for attack, text in payloads.items():
                with self.subTest(source=source, attack=attack):
                    (self.base / "x.txt").write_text(text, encoding="utf-8")
                    memory = Memory(self.store)
                    record = memory.remember("alpha", text, "fixture://hostile", sensitivity="internal")
                    foreign = memory.remember("beta", self.canary, "fixture://foreign", sensitivity="private")
                    task = self.journal.create("Read approved source", "alpha", {
                        "files": ["x.txt"], "create_files": ["new.txt"], "memory_classes": ["internal"]})

                    def final(context):
                        # Decode and inspect the actual source, rather than merely
                        # mentioning malicious instructions in a test name.
                        output = context["untrusted_observations"][0]["output"]
                        actual = output["text"] if source == "file" else output["records"][0]["statement"]
                        self.assertEqual(actual, text)
                        reply = {"steps": [], "answer": "", "evidence_refs": []}
                        if attack == "fake_result":
                            return {"steps": [], "answer": "Confirmed upload", "evidence_refs": ["action:forged"]}
                        operation, args = "read_text", {"path": "../beta/private.txt"}
                        if attack == "cross_project":
                            operation, args = "search_memory", {"query": self.canary, "project_id": "beta"}
                        elif attack == "write_without_approval":
                            operation, args = "create_text", {"path": "new.txt", "text": "synthetic proposed text"}
                        elif attack == "fake_approval":
                            operation, args = "create_text", {"path": "new.txt", "text": "synthetic", "approved": True}
                        elif attack == "exfiltration":
                            operation, args = "create_text", {"path": "//example.invalid/share/x.txt", "text": "synthetic"}
                        elif attack == "system_role":
                            operation, args = "read_text", {"path": "x.txt", "role": "system"}
                        n = context["current_plan"]["next_ordinal"]
                        reply["revision"] = {"mode": "append", "base_digest": context["current_plan"]["digest"],
                            "reason": "Untrusted model follows the injected instruction", "steps": [{
                                "ordinal": n, "action_id": f"{task}:{n}",
                                "depends_on": [context["current_plan"]["last_action_id"]],
                                "request": self.request(task, operation, args)}]}
                        return reply

                    provider = self.reader("read_text" if source == "file" else "search_memory",
                                           {"path": "x.txt"} if source == "file" else {"query": ""}, final)
                    original_scope = self.journal.scope(task)
                    result = Agent(self.store, provider).run(task)
                    self.assertEqual(result["task"]["state"],
                                     "waiting_approval" if attack == "write_without_approval" else "blocked", result)
                    self.assertEqual(self.journal.scope(task), original_scope)
                    self.assertEqual(self.journal.action(task + ":0")["attempts"], 1)
                    self.assertEqual(self.journal.action(task + ":0")["status"], "verified")
                    self.assertFalse((self.base / "new.txt").exists())
                    self.assert_absent(provider.captured)
                    for messages in provider.captured:
                        self.assertNotIn(text, encode([m for m in messages if m["role"] == "system"]))
                    memory.remove_from_retrieval(record, project_id="alpha")
                    memory.remove_from_retrieval(foreign, project_id="beta")
