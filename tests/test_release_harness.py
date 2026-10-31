import importlib.util
import json
import socket
import subprocess
import sys
from unittest.mock import Mock

from support import REPO, RuntimeCase
from test_models import chat_response, ollama_stub

spec = importlib.util.spec_from_file_location("release_harness", REPO / "tools/installed_acceptance.py")
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)


class ReleaseHarnessTests(RuntimeCase):
    def run_harness(self, endpoint):
        child = subprocess.run([sys.executable, str(REPO / "tools/installed_acceptance.py"),
            "--root", str(self.paths.root.parent / "live-fixture"), "--endpoint", endpoint],
            capture_output=True, text=True, timeout=45)
        return child.returncode, json.loads(child.stdout)

    def test_exit_and_explicit_json_success_both_required(self):
        for code, payload in ((0, {}), (0, {"passed": False}), (0, {"passed": "true"}),
                              (2, {"passed": True}), (0, {"ollama": {"reachable": False}}),
                              (0, {"passed": True, "status": "partial"})):
            with self.subTest(code=code, payload=payload):
                runner = Mock(return_value=subprocess.CompletedProcess([], code, json.dumps(payload)))
                result = harness.run_gates(self.paths.root, runner=runner)
                self.assertEqual(result["status"], "FAILED")
                self.assertFalse(result["passed"])
                self.assertEqual(runner.call_count, 2)
        for error in (ConnectionRefusedError(10061, "CANARY"), RuntimeError("CANARY"),
                      subprocess.TimeoutExpired("stub", 1)):
            result = harness.run_gates(self.paths.root, runner=Mock(side_effect=error))
            self.assertFalse(result["passed"])
            self.assertNotIn("CANARY", json.dumps(result))

    def test_refused_connection_is_nonzero_failed(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            endpoint = f"http://127.0.0.1:{sock.getsockname()[1]}"
            code, result = self.run_harness(endpoint)
        self.assertNotEqual(code, 0)
        self.assertEqual(result["status"], "FAILED")

    def test_actual_local_stub_smoke_workflow_success_and_blocked(self):
        for blocked in (False, True):
            def respond(path, body):
                if path == "/api/tags":
                    return 200, {"models": [{"name": "qwen3.5:9b"}]}
                if "format" not in body:
                    return 200, chat_response("SYNTHETIC_OK")
                content = body["messages"][-1]["content"]
                if "synthetic-smoke" in content:
                    reply = {"steps": [{"task_id": "synthetic-smoke", "capability_id": "CAP-007",
                             "operation": "read_text", "arguments": {"path": "smoke.txt"}}],
                             "answer": "", "evidence_refs": []}
                else:
                    context = json.loads(content)
                    task = context["task_id"]
                    if blocked:
                        return 200, chat_response({"steps": [], "answer": "blocked", "evidence_refs": []})
                    if context["phase"] == "plan":
                        reply = {"steps": [
                            {"task_id": task, "capability_id": "CAP-007", "operation": "read_text", "arguments": {"path": "note.txt"}},
                            {"task_id": task, "capability_id": "CAP-002", "operation": "search_memory", "arguments": {"query": "MAPLE417"}}],
                            "answer": "", "evidence_refs": []}
                    else:
                        reply = {"steps": [], "answer": "BIRCH583 MAPLE417",
                                 "evidence_refs": [f"action:{task}:0", f"action:{task}:1"]}
                return 200, chat_response(reply)

            with ollama_stub(respond) as (endpoint, requests):
                # A fresh root for each invocation; old fixture is never reused.
                child = subprocess.run([sys.executable, str(REPO / "tools/installed_acceptance.py"),
                    "--root", str(self.paths.root.parent / f"stub-{blocked}"), "--endpoint", endpoint],
                    capture_output=True, text=True, timeout=45)
            result = json.loads(child.stdout)
            self.assertEqual(child.returncode, 2 if blocked else 0, child.stdout + child.stderr)
            self.assertEqual(result["passed"], not blocked)
            self.assertTrue(result["gates"]["smoke"]["passed"])
            self.assertNotIn("CANARY_EXPIRED_921", json.dumps(requests))
