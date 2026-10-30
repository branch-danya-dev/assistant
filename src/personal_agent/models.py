"""Ollama-only M1 adapter: numeric loopback, no redirects/proxies/cloud fallback."""
from __future__ import annotations

import http.client
import io
import json
import socket
import time
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator

from .config import AgentError, specification
from .storage import encode
from .tools import DESCRIPTORS

# Conservative UTF-8 byte ceiling leaves room for framing and 1024 output tokens in 8192.
# Tokenizer-specific packing is intentionally deferred, never silently truncate source data.
MAX_CONTEXT_BYTES = 6000
MAX_RESPONSE_BYTES = 262144


class _DeadlineReader(io.RawIOBase):
    def __init__(self, sock, deadline):
        self.sock, self.deadline = sock.dup(), deadline

    def close(self):
        self.sock.close()
        super().close()

    def readable(self):
        return True

    def readinto(self, buffer):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise AgentError("ollama_timeout")
        self.sock.settimeout(remaining)
        return self.sock.recv_into(buffer)


class _DeadlineSocket:
    """Absolute deadline also covers slow/trickling response headers, not just body reads."""
    def __init__(self, sock, deadline):
        self.sock, self.deadline = sock, deadline

    def __getattr__(self, name):
        return getattr(self.sock, name)

    def makefile(self, mode):
        if mode != "rb":
            raise AgentError("unsupported_http_stream")
        return io.BufferedReader(_DeadlineReader(self.sock, self.deadline))

    def sendall(self, data):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise AgentError("ollama_timeout")
        self.sock.settimeout(remaining)
        self.sock.sendall(data)


def reply_schema(phase: str | None = None, *, constrain_tools: bool = False,
                 task_id: str | None = None) -> dict:
    schema = {"type": "object", "additionalProperties": False,
            "required": ["steps", "answer", "evidence_refs"], "properties": {
                "steps": {"type": "array", "maxItems": 8,
                          "items": specification("schemas/tool-invocation.schema.json")},
                "answer": {"type": "string", "maxLength": 12000},
                "evidence_refs": {"type": "array", "maxItems": 40,
                                  "items": {"type": "string", "maxLength": 200}}}}
    if phase == "plan":
        schema["properties"]["steps"]["minItems"] = 1
        schema["properties"]["answer"]["maxLength"] = 0
        schema["properties"]["evidence_refs"]["maxItems"] = 0
    elif phase == "final":
        schema["properties"]["steps"]["maxItems"] = 0
        schema["properties"]["answer"]["minLength"] = 1
    if constrain_tools:
        variants = []
        for definition in DESCRIPTORS:
            invocation = specification("schemas/tool-invocation.schema.json")
            invocation["properties"]["capability_id"] = {"const": definition["id"]}
            invocation["properties"]["operation"] = {"const": definition["operation"]}
            invocation["properties"]["arguments"] = definition["input_schema"]
            if task_id:
                invocation["properties"]["task_id"] = {"const": task_id}
            variants.append(invocation)
        schema["properties"]["steps"]["items"] = {"oneOf": variants}
    return schema


def validate_reply(value: object, task_id: str) -> dict:
    if not Draft202012Validator(reply_schema()).is_valid(value):
        raise AgentError("invalid_model_reply")
    if any(step["task_id"] != task_id for step in value["steps"]):
        raise AgentError("model_task_scope_mismatch")
    return value


class Ollama:
    def __init__(self, *, endpoint: str | None = None, timeout: float = 60):
        self.config = specification("model-config.json")["primary_local"]
        url = urlsplit(endpoint or self.config["endpoint"])
        if (url.scheme != "http" or url.hostname not in ("127.0.0.1", "::1")
                or url.username or url.password or url.path not in ("", "/")
                or url.query or url.fragment):
            raise AgentError("non_loopback_egress_denied")
        if self.config["provider"] != "ollama" or self.config["model"] != "qwen3.5:9b":
            raise AgentError("unapproved_model_configuration")
        if not 0 < timeout <= 120:
            raise AgentError("invalid_provider_timeout")
        self.host, self.port = url.hostname, url.port or 80
        self.timeout = timeout
        self.metrics = {}

    def _request(self, path: str, payload: dict | None = None) -> dict:
        connection = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)
        deadline = time.monotonic() + self.timeout
        response = None
        try:
            connection.connect()
            connection.sock = _DeadlineSocket(connection.sock, deadline)
            body = encode(payload).encode("utf-8") if payload is not None else None
            connection.request("POST" if body else "GET", path, body=body,
                               headers={"Content-Type": "application/json"})
            response = connection.getresponse()
            if response.status != 200:
                raise AgentError("ollama_http_error")
            length = response.getheader("Content-Length")
            if length and int(length) > MAX_RESPONSE_BYTES:
                raise AgentError("ollama_response_too_large")
            chunks, received = [], 0
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise AgentError("ollama_timeout")
                if connection.sock is not None:
                    connection.sock.settimeout(remaining)
                chunk = response.read1(min(8192, MAX_RESPONSE_BYTES + 1 - received))
                if not chunk:
                    break
                chunks.append(chunk)
                received += len(chunk)
                if received > MAX_RESPONSE_BYTES:
                    raise AgentError("ollama_response_too_large")
            value = json.loads(b"".join(chunks))
            if not isinstance(value, dict):
                raise AgentError("ollama_invalid_response")
            return value
        except (OSError, http.client.HTTPException, ValueError, socket.timeout) as exc:
            raise AgentError("ollama_unavailable_or_invalid_response") from exc
        finally:
            if response is not None:
                response.close()
            connection.close()

    def status(self) -> dict:
        response = self._request("/api/tags")
        models = response.get("models", [])
        if not isinstance(models, list):
            raise AgentError("ollama_invalid_response")
        selected = next((m for m in models if isinstance(m, dict)
                         and m.get("name") == self.config["model"]), None)
        return {"reachable": True, "model": self.config["model"], "installed": selected is not None,
                "digest": selected.get("digest") if selected else None,
                "quantization": selected.get("details", {}).get("quantization_level") if selected else None}

    def _chat(self, messages: list[dict], *, structured: bool, phase: str | None = None,
              task_id: str | None = None) -> str:
        if len(encode(messages).encode("utf-8")) > MAX_CONTEXT_BYTES:
            raise AgentError("context_budget_exhausted")
        payload = {"model": self.config["model"], "messages": messages, "stream": False, "think": False,
                   "keep_alive": "5m", "options": {"num_ctx": self.config["context_tokens_initial"],
                                                     "num_predict": 1024, "temperature": 0}}
        if structured:
            payload["format"] = reply_schema(phase, constrain_tools=True, task_id=task_id)
        response = self._request("/api/chat", payload)
        if response.get("model") != self.config["model"]:
            raise AgentError("ollama_model_mismatch")
        if response.get("done") is not True or response.get("done_reason") == "length":
            raise AgentError("ollama_incomplete_response")
        content = response.get("message", {}).get("content")
        if not isinstance(content, str) or not content.strip():
            raise AgentError("ollama_empty_response")
        self.metrics = {key: response[key] for key in
                        ("prompt_eval_count", "eval_count", "total_duration")
                        if type(response.get(key)) is int and response[key] >= 0}
        return content

    def complete(self, messages: list[dict], *, task_id: str) -> dict:
        phase = None
        try:
            context = json.loads(messages[-1]["content"]) if messages else {}
            if isinstance(context, dict):
                phase = context.get("phase")
        except (ValueError, KeyError, TypeError):
            pass
        content = self._chat(messages, structured=True, phase=phase, task_id=task_id)
        try:
            result = json.loads(content)
        except ValueError as exc:
            raise AgentError("invalid_model_json") from exc
        validate_reply(result, task_id)
        if not Draft202012Validator(reply_schema(phase, constrain_tools=True, task_id=task_id)).is_valid(result):
            raise AgentError("model_reply_wrong_phase")
        return result

    def smoke(self) -> dict:
        status = self.status()
        if not status["installed"]:
            raise AgentError("selected_model_not_installed")
        text = self._chat([{"role": "user", "content": "Reply with SYNTHETIC_OK only."}], structured=False)
        if "SYNTHETIC_OK" not in text:
            raise AgentError("text_smoke_failed")
        task_id = "synthetic-smoke"
        reply = self.complete([{"role": "user", "content":
            'Return JSON with steps containing exactly one tool intent: task_id="synthetic-smoke", '
            'capability_id="CAP-007", operation="read_text", arguments={"path":"smoke.txt"}. '
            'Set answer="" and evidence_refs=[]. Do not execute anything.'}], task_id=task_id)
        expected = {"task_id": task_id, "capability_id": "CAP-007", "operation": "read_text",
                    "arguments": {"path": "smoke.txt"}}
        if reply["steps"] != [expected]:
            raise AgentError("tool_intent_smoke_failed")
        return {**status, "text_generation": "pass", "structured_tool_intent": "pass",
                "tools_executed": 0, "metrics": self.metrics}
