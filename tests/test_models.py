import json
import socketserver
import threading
import time
import unittest
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import support  # noqa: F401

from personal_agent.config import AgentError
from personal_agent.models import Ollama


@contextmanager
def ollama_stub(responder):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def handle_request(self):
            payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
            requests.append((self.path, payload))
            status, value = responder(self.path, payload)
            body = value if isinstance(value, bytes) else json.dumps(value).encode()
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Type", "application/json")
            self.send_header("Connection", "close")
            self.send_header("Location", "https://example.invalid/no-egress")
            self.end_headers()
            self.wfile.write(body)
            self.close_connection = True

        do_GET = handle_request
        do_POST = handle_request

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def chat_response(value):
    return {"model": "qwen3.5:9b", "done": True, "done_reason": "stop",
            "message": {"content": json.dumps(value) if isinstance(value, dict) else value},
            "prompt_eval_count": 12, "eval_count": 8}


class ModelTests(unittest.TestCase):
    def test_egress_denied(self):
        with patch("http.client.HTTPConnection") as connection:
            for endpoint in ("https://example.invalid", "http://localhost:11434", "http://127.0.0.1.evil/",
                             "http://user:pass@127.0.0.1", "http://127.0.0.1/api", "http://0.0.0.0"):
                with self.subTest(endpoint=endpoint), self.assertRaises(AgentError):
                    Ollama(endpoint=endpoint)
            connection.assert_not_called()

    def test_actual_http_protocol_smoke_with_synthetic_server(self):
        def respond(path, body):
            if path == "/api/tags":
                return 200, {"models": [{"name": "qwen3.5:9b", "digest": "synthetic-digest",
                                         "details": {"quantization_level": "fixture"}}]}
            if "format" not in body:
                return 200, chat_response("SYNTHETIC_OK")
            return 200, chat_response({"steps": [{"task_id": "synthetic-smoke", "capability_id": "CAP-007",
                "operation": "read_text", "arguments": {"path": "smoke.txt"}}], "answer": "", "evidence_refs": []})
        with ollama_stub(respond) as (endpoint, requests):
            result = Ollama(endpoint=endpoint).smoke()
        self.assertEqual(result["tools_executed"], 0)
        self.assertEqual(len(requests), 3)
        self.assertEqual(requests[-1][1]["model"], "qwen3.5:9b")
        self.assertEqual(requests[-1][1]["options"]["num_ctx"], 8192)
        self.assertFalse(requests[-1][1]["stream"])

    def test_redirect_malformed_and_privilege_forgery(self):
        forged = {"steps": [{"task_id": "test", "capability_id": "CAP-007", "operation": "read_text",
                             "arguments": {"path": "x"}, "side_effect": "read"}],
                  "answer": "", "evidence_refs": []}
        for status, reply in ((302, {}), (200, b"not json"), (200, chat_response(forged)),
                               (200, {**chat_response("{}"), "done_reason": "length"})):
            with self.subTest(status=status, reply=reply):
                with ollama_stub(lambda path, body: (status, reply)) as (endpoint, requests):
                    with self.assertRaises(AgentError):
                        Ollama(endpoint=endpoint).complete([], task_id="test")
                    self.assertEqual(len(requests), 1)

    def test_context_bound_precedes_network(self):
        with patch("http.client.HTTPConnection") as connection:
            with self.assertRaises(AgentError):
                Ollama().complete([{"role": "user", "content": "x" * 6001}], task_id="test")
            connection.assert_not_called()

    def test_absolute_deadline_covers_trickling_headers(self):
        class Trickling(socketserver.BaseRequestHandler):
            def handle(self):
                self.request.recv(8192)
                try:
                    for byte in b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}":
                        self.request.sendall(bytes([byte]))
                        time.sleep(0.02)
                except OSError:
                    pass
        with socketserver.ThreadingTCPServer(("127.0.0.1", 0), Trickling) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                model = Ollama(endpoint=f"http://127.0.0.1:{server.server_address[1]}", timeout=0.12)
                started = time.monotonic()
                with self.assertRaises(AgentError):
                    model.status()
                self.assertLess(time.monotonic() - started, 0.8)
            finally:
                server.shutdown()
                thread.join(timeout=5)

    def test_plan_cannot_be_replaced_by_an_unexecuted_answer(self):
        reply = {"steps": [], "answer": "I did it", "evidence_refs": []}
        with ollama_stub(lambda path, body: (200, chat_response(reply))) as (endpoint, _):
            with self.assertRaisesRegex(AgentError, "model_reply_wrong_phase"):
                Ollama(endpoint=endpoint).complete(
                    [{"role": "user", "content": '{"phase":"plan"}'}], task_id="test")
