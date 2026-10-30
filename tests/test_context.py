import hashlib
import json
from unittest.mock import patch

from support import RuntimeCase
from test_models import chat_response, ollama_stub

from personal_agent.config import AgentError
from personal_agent.context import message_bytes
from personal_agent.identity import Identity
from personal_agent.models import MAX_CONTEXT_BYTES, Ollama
from personal_agent.orchestrator import Agent
from personal_agent.storage import Store


class ReceiptProvider:
    """Synthetic provider deliberately makes a false claim to test trusted finalization."""
    def __init__(self, operation="read_text", text=""):
        self.operation, self.text, self.messages = operation, text, []

    def complete(self, messages, *, task_id):
        self.messages.append(messages)
        context = json.loads(messages[-1]["content"])
        if context["phase"] == "plan":
            args = {"path": "note.txt"}
            if self.operation == "create_text":
                args["text"] = self.text
            return {"steps": [{"task_id": task_id, "capability_id":
                    "CAP-008" if self.operation == "create_text" else "CAP-007",
                    "operation": self.operation, "arguments": args}], "answer": "", "evidence_refs": []}
        return {"steps": [], "answer": "FALSE_FULL_ANALYSIS_SUCCESS",
                "evidence_refs": [o["evidence_ref"] for o in context["untrusted_observations"]]}


class ContextTests(RuntimeCase):
    def setUp(self):
        super().setUp()
        Identity(self.paths).initialize()
        self.base = self.paths.project_workspace("alpha")
        self.base.mkdir()

    def read_task(self, text):
        (self.base / "note.txt").write_bytes(text.encode("utf-8"))
        return self.journal.create("Read and analyze all of note.txt", "alpha",
                                   {"files": ["note.txt"], "memory_classes": ["public"]})

    def check_saved_read(self, task, text, provider, result):
        self.assertEqual(result["task"]["state"], "partial", result)
        self.assertEqual(result["result"]["semantic_analysis"], "incomplete")
        self.assertNotIn("FALSE_FULL_ANALYSIS_SUCCESS", json.dumps(result))
        action = self.journal.action(f"{task}:0")
        saved = json.loads(action["result"])
        self.assertEqual(saved["text"], text)
        self.assertEqual(saved["bytes"], len(text.encode("utf-8")))
        self.assertEqual(saved["sha256"], hashlib.sha256(text.encode("utf-8")).hexdigest())
        self.assertEqual(action["attempts"], 1)
        self.assertTrue(all(message_bytes(m) <= MAX_CONTEXT_BYTES for m in provider.messages))
        view = json.loads(provider.messages[-1][-1]["content"])["untrusted_observations"][0]
        self.assertNotIn("text", view["output"])
        self.assertEqual(view["output"]["sha256"], saved["sha256"])
        self.assertEqual(view["content_visibility"], "receipt_only")
        self.assertEqual(view["result_digest"], self.journal.evidence(task, f"action:{task}:0", "alpha")["result_digest"])

    def test_8k_and_32k_reads_keep_full_evidence_without_context_deadlock(self):
        for length in (8192, 32768):
            with self.subTest(length=length):
                text = "x" * length
                task = self.read_task(text)
                provider = ReceiptProvider()
                result = Agent(self.store, provider).run(task)
                self.check_saved_read(task, text, provider, result)
                with Store(self.paths) as reopened:
                    self.assertEqual(Agent(reopened, provider).journal.get(task)["state"], "partial")

    def test_utf8_and_nested_json_escaping_count_toward_actual_prompt_budget(self):
        text = ('я"\\\n' * 4000)  # 20,000 UTF-8 bytes; substantially more nested JSON bytes.
        task = self.read_task(text)
        provider = ReceiptProvider()
        result = Agent(self.store, provider).run(task)
        self.check_saved_read(task, text, provider, result)

    def test_small_read_is_fully_visible_not_an_excerpt(self):
        text = "Entire synthetic source."
        task = self.read_task(text)
        provider = ReceiptProvider()
        result = Agent(self.store, provider).run(task)
        self.assertEqual(result["task"]["state"], "completed", result)
        view = json.loads(provider.messages[-1][-1]["content"])["untrusted_observations"][0]
        self.assertEqual(view["content_visibility"], "full")
        self.assertEqual(view["output"]["text"], text)

    def test_large_create_arguments_not_repeated_and_append_revision_preserves_approval(self):
        for length in (8192, 32768):
            with self.subTest(length=length):
                class AppendProvider(ReceiptProvider):
                    revised = False

                    def complete(provider, messages, *, task_id):
                        reply = super().complete(messages, task_id=task_id)
                        if not reply["steps"] and not provider.revised:
                            provider.revised = True
                            current = json.loads(messages[-1]["content"])["current_plan"]
                            n = current["next_ordinal"]
                            reply["revision"] = {"mode": "append", "base_digest": current["digest"],
                                "reason": "Synthetic model proposes a continuation without old payloads",
                                "steps": [{"ordinal": n, "action_id": f"{task_id}:{n}",
                                    "depends_on": [current["last_action_id"]], "request": {
                                        "task_id": task_id, "capability_id": "CAP-002",
                                        "operation": "search_memory", "arguments": {"query": "synthetic"}}}]}
                        return reply
                provider = AppendProvider("create_text", "C" * length)
                task = self.journal.create("Create the synthetic fixture", "alpha", {
                    "files": [], "create_files": ["note.txt"], "memory_classes": ["public"]})
                agent = Agent(self.store, provider)
                waiting = agent.run(task)
                first = waiting["actions"][0]
                self.journal.approve(first["approval_id"], first["digest"])
                before = self.journal.plans.current(task)["steps"][0]
                result = agent.run(task)
                self.assertEqual(result["task"]["state"], "completed", result)
                self.assertEqual((self.base / "note.txt").read_bytes(), b"C" * length)
                self.assertEqual(self.journal.plans.current(task)["steps"][0], before)
                self.assertEqual(self.journal.action(first["id"])["attempts"], 1)
                self.assertEqual(self.journal.approval(first["approval_id"])["status"], "consumed")
                self.assertEqual(result["plan"]["revision"], 1)
                self.assertTrue(all(message_bytes(m) <= MAX_CONTEXT_BYTES for m in provider.messages))
                self.assertNotIn("C" * 100, json.dumps(provider.messages))
                self.assertNotIn("FALSE_FULL_ANALYSIS_SUCCESS", json.dumps(result))
                (self.base / "note.txt").unlink()  # Explicit isolated test fixture, not a runtime tool.

    def test_pause_then_reopen_projects_saved_read_without_reexecution(self):
        class PauseOnce(ReceiptProvider):
            paused = False

            def complete(provider, messages, *, task_id):
                reply = super().complete(messages, task_id=task_id)
                if not reply["steps"] and not provider.paused:
                    provider.paused = True
                    raise AgentError("operation_timeout_exhausted")
                return reply
        text = "R" * 32768
        task, provider = self.read_task(text), PauseOnce()
        self.assertEqual(Agent(self.store, provider).run(task)["task"]["state"], "paused")
        (self.base / "note.txt").write_text("Changed after saved verification")
        with Store(self.paths) as reopened:
            agent = Agent(reopened, provider)
            with patch.object(agent, "_tool", side_effect=AssertionError("replayed")):
                result = agent.run(task, resume=True)
        self.check_saved_read(task, text, provider, result)

    def test_receipt_overflow_finishes_partial_without_calling_model_or_replaying(self):
        task = self.read_task("small")
        self.journal.start(task)
        requests = [{"task_id": task, "capability_id": "CAP-007", "operation": "read_text",
                     "arguments": {"path": "note.txt"}}] * 40
        self.journal.set_plan(task, requests)
        for i, request in enumerate(requests):
            action = self.journal.prepare(task, i, request, "read", "workspace/alpha/note.txt")
            self.journal.dispatch(action, approval_required=False)
            self.journal.finish(action, {"path": "note.txt", "text": "small", "bytes": 5,
                "sha256": hashlib.sha256(b"small").hexdigest(), "identity": [1, 2]})
        self.journal.transition(task, "paused")
        provider = ReceiptProvider()
        agent = Agent(self.store, provider)
        with patch.object(agent, "_model", side_effect=AssertionError("oversized model request")):
            result = agent.run(task, resume=True)
        self.assertEqual(result["task"]["state"], "partial", result)
        self.assertEqual(len(result["result"]["evidence_refs"]), 40)
        self.assertEqual(result["result"]["model_context"]["prompt_bytes"], 0)

    def test_http_adapter_receives_only_bounded_prompts_for_maximum_file(self):
        task = self.read_task("H" * 32768)
        provider = ReceiptProvider()
        def respond(path, body):
            return 200, chat_response(provider.complete(body["messages"], task_id=task))
        with ollama_stub(respond) as (endpoint, requests):
            result = Agent(self.store, Ollama(endpoint=endpoint)).run(task)
        self.check_saved_read(task, "H" * 32768, provider, result)
        self.assertEqual(len(requests), 2)

    def test_append_rejects_stale_digest_and_duplicate_old_action(self):
        task = self.read_task("small")
        self.journal.start(task)
        request = {"task_id": task, "capability_id": "CAP-007", "operation": "read_text",
                   "arguments": {"path": "note.txt"}}
        self.journal.set_plan(task, [request])
        current = self.journal.plans.current(task)
        proposal = {"mode": "append", "base_digest": "0" * 64, "reason": "fixture",
                    "steps": current["steps"]}
        agent = Agent(self.store, ReceiptProvider())
        with self.assertRaisesRegex(AgentError, "stale_plan_revision"):
            self.journal.plans.revise(task, proposal, agent.registry)
        proposal["base_digest"] = current["digest"]
        with self.assertRaisesRegex(AgentError, "unresolved_plan_dependencies"):
            self.journal.plans.revise(task, proposal, agent.registry)
