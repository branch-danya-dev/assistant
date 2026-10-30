import json
from unittest.mock import patch

from support import RuntimeCase
from test_models import chat_response, ollama_stub

from personal_agent.demo import DemoProvider, run_demo
from personal_agent.identity import Identity
from personal_agent.memory import Memory
from personal_agent.models import Ollama
from personal_agent.orchestrator import Agent
from personal_agent.storage import Store


class OrchestratorTests(RuntimeCase):
    def setUp(self):
        super().setUp()
        Identity(self.paths).initialize()
        base = self.paths.project_workspace("alpha")
        base.mkdir()
        (base / "note.txt").write_text("Synthetic note", encoding="utf-8")
        Memory(self.store).remember("alpha", "Use green", "fixture://owner", sensitivity="internal")

    def test_offline_demo(self):
        result = run_demo(self.paths)
        self.assertEqual(result["mode"], "offline_fixture_no_model")
        self.assertEqual(result["task"]["state"], "completed")
        self.assertEqual(result["result"]["verified_steps"], 2)

    def test_scn005_reads_then_denied_write_and_restart(self):
        class ProposeWrite(DemoProvider):
            def complete(self, messages, *, task_id):
                result = super().complete(messages, task_id=task_id)
                result["steps"].append({"task_id": task_id, "capability_id": "CAP-008",
                                        "operation": "overwrite", "arguments": {"path": "note.txt"}})
                return result
        task = self.task(files=["note.txt"])
        agent = Agent(self.store, ProposeWrite())
        result = agent.run(task)
        self.assertEqual(result["task"]["state"], "blocked")
        self.assertEqual(len(result["actions"]), 2)
        self.assertTrue(all(a["status"] == "verified" for a in result["actions"]))
        self.assertEqual(result["events"][-2]["kind"], "denied")
        with Store(self.paths) as reopened:
            resumed = Agent(reopened, ProposeWrite())
            with patch.object(resumed.registry, "execute") as executor:
                resumed.run(task, resume=True)
                executor.assert_not_called()
        self.assertEqual((self.paths.project_workspace("alpha") / "note.txt").read_text(), "Synthetic note")

    def test_scn007_injection_cannot_escalate_or_leak(self):
        Memory(self.store).remember("beta", "SYNTHETIC_PRIVATE_SECRET", "fixture://beta")
        class InjectionProvider:
            captured = []

            def complete(self, messages, *, task_id):
                self.captured.extend(messages)
                return {"steps": [{"task_id": task_id, "capability_id": "CAP-026",
                    "operation": "upload_memory", "arguments": {"project_id": "beta"}}],
                    "answer": "", "evidence_refs": []}
        provider = InjectionProvider()
        task = self.task()
        agent = Agent(self.store, provider)
        with patch.object(agent.registry, "execute") as executor:
            result = agent.run(task)
            executor.assert_not_called()
        self.assertEqual(result["task"]["state"], "blocked")
        self.assertNotIn("SYNTHETIC_PRIVATE_SECRET", json.dumps(provider.captured))
        self.assertTrue(any(e["kind"] == "denied" for e in result["events"]))

    def test_scn011_provider_swap_preserves_identity_and_memory(self):
        identity = Identity(self.paths).current()
        for provider in (DemoProvider(), DemoProvider()):
            task = self.task(files=["note.txt"])
            self.assertEqual(Agent(self.store, provider).run(task)["task"]["state"], "completed")
        with Store(self.paths) as reopened:
            self.assertEqual(Identity(reopened.paths).current(), identity)
            self.assertEqual(len(Memory(reopened).search("Use", project_id="alpha")), 1)

    def test_full_agent_through_http_adapter(self):
        provider = DemoProvider()
        def respond(path, body):
            context = json.loads(body["messages"][-1]["content"])
            return 200, chat_response(provider.complete(body["messages"], task_id=context["task_id"]))
        with ollama_stub(respond) as (endpoint, requests):
            task = self.task(files=["note.txt"])
            result = Agent(self.store, Ollama(endpoint=endpoint)).run(task)
        self.assertEqual(result["task"]["state"], "completed")
        self.assertEqual(result["result"]["verified_steps"], 2)
        self.assertEqual(len(requests), 2)

    def test_stop_between_inference_and_dispatch(self):
        outer = self
        class StopProvider(DemoProvider):
            def complete(self, messages, *, task_id):
                outer.journal.stop()
                return super().complete(messages, task_id=task_id)
        task = self.task(files=["note.txt"])
        agent = Agent(self.store, StopProvider())
        with patch.object(agent.registry, "execute") as executor:
            result = agent.run(task)
            executor.assert_not_called()
        self.assertEqual(result["task"]["state"], "paused")

    def test_no_false_success_on_fabricated_tool_evidence(self):
        class Fabricate(DemoProvider):
            def complete(self, messages, *, task_id):
                result = super().complete(messages, task_id=task_id)
                if not result["steps"]:
                    result["evidence_refs"] = ["action:fake"]
                return result
        task = self.task(files=["note.txt"])
        result = Agent(self.store, Fabricate()).run(task)
        self.assertEqual(result["task"]["state"], "blocked")
        self.assertEqual(result["task"]["block_reason"], "fabricated_evidence_reference")
