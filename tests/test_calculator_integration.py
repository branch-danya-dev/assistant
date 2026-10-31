import copy
import io
import json
import subprocess
import sys
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from support import RuntimeCase
from test_calculator import calculation, costs, literal
from test_models import chat_response, ollama_stub

from personal_agent import cli
from personal_agent.calculator import execute
from personal_agent.config import AgentError
from personal_agent.identity import Identity
from personal_agent.journal import Journal
from personal_agent.memory import Memory
from personal_agent.models import Ollama
from personal_agent.orchestrator import Agent
from personal_agent.storage import Store, encode
from personal_agent.tools import Registry


class NumericProvider:
    def __init__(self, arguments=None, operation="calculate", repeat=1):
        self.arguments = arguments or calculation()
        self.operation, self.repeat = operation, repeat
        self.messages = []

    def complete(self, messages, *, task_id):
        self.messages.extend(messages)
        context = json.loads(messages[-1]["content"])
        if context["phase"] == "plan":
            return {"steps": [{"task_id": task_id, "capability_id": "CAP-009",
                "operation": self.operation, "arguments": self.arguments} for _ in range(self.repeat)],
                "answer": "", "evidence_refs": []}
        return {"steps": [], "answer": "Verified numerical evidence.",
                "evidence_refs": [f"action:{task_id}:{i}" for i in range(self.repeat)]}


class CalculatorIntegrationTests(RuntimeCase):
    def setUp(self):
        super().setUp()
        Identity(self.paths).initialize()

    def numeric_task(self, enabled=True, private=False, budget=None):
        return self.journal.create("Synthetic calculation", "alpha", {"files": [], "memory_classes": [],
            "experimental_calculator": enabled, "intent_class": "private" if private else "internal"},
            budget=budget)

    def test_opt_in_real_worker_evidence_no_effect_approval_or_network(self):
        for operation, arguments in (("calculate", calculation()), ("cost_scenarios", costs())):
            task = self.numeric_task()
            provider = NumericProvider(arguments, operation)
            with patch("personal_agent.models.Ollama._request", side_effect=AssertionError("network")):
                result = Agent(self.store, provider).run(task)
            self.assertEqual(result["task"]["state"], "completed", result)
            action = self.journal.action(f"{task}:0")
            self.assertEqual((action["effect"], action["attempts"], action["approval_id"]), ("read", 1, None))
            self.assertEqual(json.loads(action["result"]), execute(operation, arguments))
            final = json.loads(provider.messages[-1]["content"])
            self.assertEqual(final["untrusted_observations"][0]["content_visibility"], "full")
            self.assertEqual(self.store.connection.execute("SELECT count(*) FROM approvals").fetchone()[0], 0)
            self.assertEqual(result["actions"][0]["evidence"]["output"]["contract"], "decimal-v1")

    def test_disabled_scope_foreign_task_stale_receipt_and_forged_privilege(self):
        for kind in ("disabled", "foreign", "expired", "changed_scope", "permission"):
            task = self.numeric_task(enabled=kind != "disabled")
            provider = NumericProvider()
            agent = Agent(self.store, provider)
            if kind == "expired":
                self.store.connection.execute("UPDATE data_admissions SET expires_at='2000-01-01T00:00:00Z' WHERE object_id=?", (task,))
            if kind == "changed_scope":
                scope = self.journal.scope(task)
                scope["experimental_calculator"] = False
                self.store.connection.execute("UPDATE tasks SET scope=? WHERE id=?", (encode(scope), task))
            original = provider.complete

            def forge(messages, *, task_id):
                value = original(messages, task_id=task_id)
                if value["steps"] and kind == "foreign":
                    value["steps"][0]["task_id"] = "other"
                if value["steps"] and kind == "permission":
                    value["steps"][0]["approval_required"] = False
                return value

            with patch.object(provider, "complete", side_effect=forge), patch.object(agent, "_tool") as tool:
                result = agent.run(task)
                tool.assert_not_called()
            self.assertEqual(result["task"]["state"], "blocked")
            self.assertEqual(self.store.connection.execute("SELECT count(*) FROM actions WHERE task_id=?", (task,)).fetchone()[0], 0)

    def test_forged_worker_result_never_becomes_verified_or_completed(self):
        task = self.numeric_task()
        agent = Agent(self.store, NumericProvider())
        receipt = execute("calculate", calculation())
        receipt["result"]["number"]["value"] = "99.00"
        with patch.object(agent, "_tool", return_value=receipt):
            result = agent.run(task)
        self.assertEqual(result["task"]["state"], "blocked")
        self.assertEqual(result["task"]["block_reason"], "calculator_verification_failed")
        self.assertEqual(self.journal.action(f"{task}:0")["status"], "pending")
        self.assertIsNone(self.journal.action(f"{task}:0")["result"])
        self.assertFalse(any(e["kind"] == "verified" for e in self.journal.events(task)))

    def test_actual_model_http_intent_to_trusted_tool_to_final_evidence(self):
        provider = NumericProvider()

        def respond(path, body):
            context = json.loads(body["messages"][-1]["content"])
            return 200, chat_response(provider.complete(body["messages"], task_id=context["task_id"]))

        with ollama_stub(respond) as (endpoint, requests):
            task = self.numeric_task()
            result = Agent(self.store, Ollama(endpoint=endpoint)).run(task)
        self.assertEqual(result["task"]["state"], "completed", result)
        self.assertEqual(len(requests), 2)
        self.assertIn("cost_scenarios", json.dumps(requests[0][1]["format"]))
        self.assertEqual(json.loads(self.journal.action(f"{task}:0")["result"])["result"]["number"]["value"], "0.30")

    def test_arithmetic_injection_cannot_request_code_send_or_owner_approval(self):
        for operation, arguments in (("approve", {}), ("send", {}), ("exec", {}),
            ("calculate", calculation(literal("1; create file; approve any digest"))),
            ("calculate", {**calculation(), "side_effect": "read"})):
            task = self.numeric_task()
            agent = Agent(self.store, NumericProvider(arguments, operation))
            with patch.object(agent, "_tool") as tool:
                result = agent.run(task)
                tool.assert_not_called()
            self.assertEqual(result["task"]["state"], "blocked")
        self.assertEqual(self.store.connection.execute("SELECT count(*) FROM approvals").fetchone()[0], 0)

    def test_actual_process_crash_before_ack_and_after_verified_never_replays_verified(self):
        program = '''
import json, os, sys
from personal_agent.config import Paths
from personal_agent.storage import Store
from personal_agent.journal import Journal
from personal_agent.orchestrator import Agent
class Provider:
    def complete(self, messages, *, task_id):
        context=json.loads(messages[-1]['content'])
        if context['phase']=='plan':
            return {'steps':[{'task_id':task_id,'capability_id':'CAP-009','operation':'calculate','arguments':json.loads(sys.argv[4])}],'answer':'','evidence_refs':[]}
        return {'steps':[],'answer':'verified','evidence_refs':['action:'+task_id+':0']}
setattr(Journal, sys.argv[3], lambda *a, **k: os._exit(23))
with Store(Paths(sys.argv[1])) as store:
    Agent(store,Provider()).run(sys.argv[2])
'''
        for point, attempts in (("finish", 2), ("complete", 1)):
            task = self.numeric_task()
            child = subprocess.run([sys.executable, "-c", program, str(self.paths.root), task,
                                    point, json.dumps(calculation())], capture_output=True, timeout=20)
            self.assertEqual(child.returncode, 23, child.stderr)
            with Store(self.paths) as reopened:
                journal = Journal(reopened)
                result = Agent(reopened, NumericProvider()).run(task, resume=True)
                self.assertEqual(result["task"]["state"], "completed", result)
                action = journal.action(f"{task}:0")
                self.assertEqual(action["attempts"], attempts)
                self.assertEqual(json.loads(action["result"]), execute("calculate", calculation()))
                self.assertIsNone(action["approval_id"])

    def test_tool_budget_preserves_verified_result_without_replay(self):
        task = self.numeric_task(budget={"tool_limit": 1})
        agent = Agent(self.store, NumericProvider(repeat=2))
        result = agent.run(task)
        self.assertEqual(result["task"]["state"], "paused")
        self.assertEqual(result["task"]["block_reason"], "tool_budget_exhausted")
        agent.run(task, resume=True)
        self.assertEqual(self.journal.action(f"{task}:0")["attempts"], 1)
        self.assertEqual(self.journal.action(f"{task}:1")["attempts"], 0)

    def test_real_timeout_reaps_calculator_worker_and_bounded_retry(self):
        from dataclasses import asdict

        from personal_agent.bounded import run_worker
        task = self.numeric_task()
        agent = Agent(self.store, NumericProvider())
        popen = subprocess.Popen
        children = []

        def sleep(command, **kwargs):
            process = popen([sys.executable, "-c", "import time; time.sleep(30)"], **kwargs)
            children.append(process)
            return process

        def delayed(resolved, state, scope):
            with patch("personal_agent.bounded.subprocess.Popen", side_effect=sleep):
                return run_worker(self.paths, {"kind": "tool", "resolved": asdict(resolved),
                    "task": {k: state[k] for k in ("task_id", "project_id")}, "scope": scope},
                    timeout=0.2, journal=self.journal, task_id=task)

        with patch.object(agent, "_tool", side_effect=delayed):
            result = agent.run(task)
        self.assertEqual(result["task"]["state"], "paused")
        self.assertEqual(result["task"]["block_reason"], "operation_timeout_exhausted")
        self.assertTrue(all(p.poll() is not None for p in children))
        result = agent.run(task, resume=True)
        self.assertEqual(result["task"]["state"], "completed")
        self.assertEqual(self.journal.action(f"{task}:0")["attempts"], 2)

    def test_cli_input_duplicate_fields_bytes_and_private_diagnostics(self):
        source = self.paths.root.parent / "input.json"
        for private in (False, True):
            source.write_text(json.dumps(calculation(literal("81731773"))), encoding="utf-8")
            args = ["--root", str(self.paths.root), "calculate", "--input", str(source),
                    "--project", "alpha", "--experimental-calculator"]
            if private:
                args += ["--private-intent"]
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                code = cli.main(args)
            self.assertEqual((code, err.getvalue()), (0, ""))
            if private:
                self.assertNotIn("81731773", out.getvalue())
            else:
                self.assertEqual(json.loads(out.getvalue())["calculations"][0]["result"]["number"]["value"], "81731773.00")
        for data in ('{"scale":2,"scale":3}', 'x' * 4097, '{"expression":"CANARY"}'):
            source.write_text(data, encoding="utf-8")
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                self.assertEqual(cli.main(args), 2)
            self.assertNotIn("CANARY", out.getvalue() + err.getvalue())
        with redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(args[:-2]), 2)
        valid = json.dumps(calculation())
        source.write_text(valid + " " * (4096 - len(valid)), encoding="utf-8")
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(args), 0)
        with source.open("a", encoding="utf-8") as output:
            output.write(" ")
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(args), 2)

    def test_registry_rejects_descriptor_forgery_and_foreign_scope(self):
        task = self.numeric_task()
        request = {"task_id": task, "capability_id": "CAP-009", "operation": "calculate", "arguments": calculation()}
        registry = Registry(self.paths, Memory(self.store))
        state, scope = self.journal.get(task), self.journal.scope(task)
        resolved = registry.resolve(request, state, scope)
        self.assertEqual(resolved.descriptor["side_effect"], "read")
        self.assertFalse(resolved.descriptor["approval_required"])
        forged = copy.deepcopy(resolved)
        forged.descriptor["side_effect"] = "workspace_write"
        # Use a fresh registry so mutating the test's shared descriptor cannot authorize it.
        with self.assertRaises(AgentError):
            Registry(self.paths, Memory(self.store)).execute(forged, state, scope)
        with self.assertRaises(AgentError):
            registry.resolve(request, {**state, "project_id": "foreign"}, scope)
