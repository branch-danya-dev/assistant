"""Closed, trusted M1 registry. No dynamic plugin loading or model-defined permissions."""
from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from jsonschema import Draft202012Validator

from .config import AgentError, Paths, safe_relative, validate
from .memory import Memory
from .storage import encode

MAX_FILE_BYTES = 32768


def descriptor(capability: str, operation: str, field: str) -> dict:
    if operation == "read_text":
        output_schema = {"type": "object", "additionalProperties": False,
                         "required": ["path", "text", "sha256", "bytes"], "properties": {
                             "path": {"type": "string"}, "text": {"type": "string"},
                             "sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                             "bytes": {"type": "integer", "minimum": 0, "maximum": MAX_FILE_BYTES}}}
    else:
        output_schema = {"type": "object", "additionalProperties": False,
                         "required": ["records"], "properties": {
                             "records": {"type": "array", "maxItems": 20, "items": {"type": "object"}}}}
    return dict(id=capability, version="1.0", operation=operation, side_effect="read",
                scope="owner_task_scope", timeout_seconds=5, approval_required=False,
                input_schema={"type": "object", "additionalProperties": False,
                              "required": [field], "properties": {
                                  field: {"type": "string", "maxLength": 1000}}},
                output_schema=output_schema, verifier="independent_read_verifier",
                idempotent=True, retry_policy="explicit_resume_max_2", effect_resolver="m1_closed_registry")


DESCRIPTORS = (
    descriptor("CAP-007", "read_text", "path"),
    descriptor("CAP-002", "search_memory", "query"),
)


@dataclass(frozen=True)
class Resolved:
    request: dict
    descriptor: dict
    resource: str


def read_text(paths: Paths, project_id: str, relative: str) -> dict:
    """Validate before open and inspect the opened handle before reading bytes."""
    relative = safe_relative(relative)
    base = paths.project_workspace(project_id)
    candidate = paths.under((base / relative).relative_to(paths.root).as_posix())
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(candidate, flags)
    except OSError as exc:
        raise AgentError("file_open_failed") from exc
    try:
        metadata = os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise AgentError("non_regular_or_linked_file_denied")
        if metadata.st_size > MAX_FILE_BYTES:
            raise AgentError("file_size_exceeded")
        if os.name == "nt":
            import ctypes
            import msvcrt
            from ctypes import wintypes
            api = ctypes.WinDLL("kernel32", use_last_error=True).GetFinalPathNameByHandleW
            api.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
            api.restype = wintypes.DWORD
            buffer = ctypes.create_unicode_buffer(32768)
            size = api(msvcrt.get_osfhandle(fd), buffer, len(buffer), 0)
            if size == 0 or size >= len(buffer):
                raise AgentError("file_handle_verification_failed")
            actual = Path(buffer.value.removeprefix("\\\\?\\"))
        else:
            # Linux CI/host: inspect descriptor, not a second untrusted pathname resolution.
            actual = Path(os.readlink(f"/proc/self/fd/{fd}"))
        if actual != candidate or not actual.is_relative_to(base):
            raise AgentError("opened_file_outside_scope")
        paths.under(candidate.relative_to(paths.root).as_posix())
        chunks = []
        remaining = MAX_FILE_BYTES + 1
        while remaining:
            chunk = os.read(fd, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        if len(data) > MAX_FILE_BYTES:
            raise AgentError("file_size_exceeded")
        try:
            text = data.decode("utf-8")
        except UnicodeError as exc:
            raise AgentError("utf8_text_required") from exc
        return {"path": relative, "text": text, "sha256": hashlib.sha256(data).hexdigest(),
                "bytes": len(data)}
    finally:
        os.close(fd)


class Registry:
    def __init__(self, paths: Paths, memory: Memory):
        self.paths, self.memory = paths, memory
        self.descriptors = {(d["id"], d["operation"]): d for d in DESCRIPTORS}
        for definition in self.descriptors.values():
            validate("tool-descriptor", definition)

    def resolve(self, request: dict, task: dict, scope: dict) -> Resolved:
        validate("tool-invocation", request)
        if request["task_id"] != task["task_id"]:
            raise AgentError("task_scope_mismatch")
        definition = self.descriptors.get((request["capability_id"], request["operation"]))
        if not definition:
            raise AgentError("unregistered_operation")
        if not Draft202012Validator(definition["input_schema"]).is_valid(request["arguments"]):
            raise AgentError("invalid_tool_arguments")
        normalized = json.loads(encode(request))
        if request["operation"] == "read_text":
            relative = safe_relative(request["arguments"]["path"])
            if relative not in scope.get("files", []):
                raise AgentError("file_not_in_owner_scope")
            base = self.paths.project_workspace(task["project_id"])
            candidate = self.paths.under((base / relative).relative_to(self.paths.root).as_posix())
            normalized["arguments"]["path"] = relative
            resource = candidate.relative_to(self.paths.root).as_posix()
        else:
            resource = f"memory:{task['project_id']}"
        return Resolved(normalized, definition, resource)

    def execute(self, resolved: Resolved, task: dict, scope: dict) -> dict:
        # Resolve again immediately at adapter entry; external data never creates authorization.
        checked = self.resolve(resolved.request, task, scope)
        if checked != resolved:
            raise AgentError("resolved_target_changed")
        request = checked.request
        if request["operation"] == "read_text":
            return read_text(self.paths, task["project_id"], request["arguments"]["path"])
        return {"records": self.memory.search(request["arguments"]["query"],
                 project_id=task["project_id"], allowed_classes=tuple(scope["memory_classes"]))}

    def verify(self, resolved: Resolved, result: dict, task: dict, scope: dict):
        # Independently re-observe the bounded local source. A changed source is not success.
        if result != self.execute(resolved, task, scope):
            raise AgentError("source_changed_during_verification")
        if not Draft202012Validator(resolved.descriptor["output_schema"]).is_valid(result):
            raise AgentError("invalid_tool_output")
