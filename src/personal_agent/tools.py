"""Closed trusted registry; execution and side-effect-free observation are separate ports."""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass

from jsonschema import Draft202012Validator

from .config import AgentError, Paths, safe_relative, validate
from .memory import Memory
from .safe_fs import MAX_FILE_BYTES, create_text, observe
from .storage import encode


def descriptor(capability: str, operation: str, field: str) -> dict:
    create = operation == "create_text"
    if operation in ("read_text", "create_text"):
        output_schema = {"type": "object", "additionalProperties": False,
                         "required": ["path", "sha256", "bytes", "identity"], "properties": {
                             "path": {"type": "string"},
                             "identity": {"type": "array", "minItems": 2, "maxItems": 2,
                                          "items": {"type": "integer"}},
                             "sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                             "bytes": {"type": "integer", "minimum": 0, "maximum": MAX_FILE_BYTES}}}
        if not create:
            output_schema["required"].append("text")
            output_schema["properties"]["text"] = {"type": "string", "maxLength": MAX_FILE_BYTES}
    else:
        output_schema = {"type": "object", "additionalProperties": False,
                         "required": ["records"], "properties": {
                             "records": {"type": "array", "maxItems": 20, "items": {"type": "object"}}}}
    inputs = {"type": "object", "additionalProperties": False,
              "required": [field], "properties": {field: {"type": "string", "maxLength": 1000}}}
    if create:
        inputs["required"].append("text")
        inputs["properties"]["text"] = {"type": "string", "maxLength": MAX_FILE_BYTES}
    return dict(id=capability, version="1.1", operation=operation,
                side_effect="workspace_write" if create else "read", scope="owner_task_scope",
                timeout_seconds=5, approval_required=create, input_schema=inputs,
                output_schema=output_schema, verifier="side_effect_free_observer",
                idempotent=not create, retry_policy="never" if create else "explicit_resume_max_2",
                effect_resolver="m1_closed_registry")


DESCRIPTORS = (descriptor("CAP-007", "read_text", "path"),
               descriptor("CAP-002", "search_memory", "query"),
               descriptor("CAP-008", "create_text", "path"))


@dataclass(frozen=True)
class Resolved:
    request: dict
    descriptor: dict
    resource: str


def read_text(paths: Paths, project_id: str, relative: str) -> dict:
    return observe(paths, project_id, relative)


class Registry:
    def __init__(self, paths: Paths, memory: Memory):
        self.paths, self.memory = paths, memory
        self.descriptors = {(d["id"], d["operation"]): d for d in DESCRIPTORS}
        for definition in self.descriptors.values():
            validate("tool-descriptor", definition)

    def resolve(self, request: dict, task: dict, scope: dict) -> Resolved:
        """Pure authorization; blocking filesystem calls belong inside the bounded worker."""
        validate("tool-invocation", request)
        if request["task_id"] != task["task_id"]:
            raise AgentError("task_scope_mismatch")
        definition = self.descriptors.get((request["capability_id"], request["operation"]))
        if not definition:
            raise AgentError("unregistered_operation")
        if not Draft202012Validator(definition["input_schema"]).is_valid(request["arguments"]):
            raise AgentError("invalid_tool_arguments")
        normalized = json.loads(encode(request))
        if request["operation"] in ("read_text", "create_text"):
            relative = safe_relative(request["arguments"]["path"])
            create = request["operation"] == "create_text"
            if relative not in scope.get("create_files" if create else "files", []):
                raise AgentError("file_not_in_owner_scope")
            if create:
                if os.name != "nt" and "/" in relative:
                    raise AgentError("nested_create_requires_windows")
                if relative not in scope.get("create_bindings", {}):
                    raise AgentError("workspace_binding_required")
                if len(request["arguments"]["text"].encode("utf-8")) > MAX_FILE_BYTES:
                    raise AgentError("file_size_exceeded")
            normalized["arguments"]["path"] = relative
            resource = f"{self.paths.config['layout']['workspace']}/{task['project_id']}/{relative}"
        else:
            resource = f"memory:{task['project_id']}"
        return Resolved(normalized, definition, resource)

    def _checked(self, resolved, task, scope):
        if self.resolve(resolved.request, task, scope) != resolved:
            raise AgentError("resolved_target_changed")

    def execute(self, resolved: Resolved, task: dict, scope: dict) -> dict:
        self._checked(resolved, task, scope)
        request = resolved.request
        args = request["arguments"]
        if request["operation"] == "create_text":
            return create_text(self.paths, task["project_id"], args["path"], args["text"],
                               scope["create_bindings"][args["path"]])
        return self.observe(resolved, task, scope)

    def observe(self, resolved: Resolved, task: dict, scope: dict) -> dict:
        """Read/re-observe only. No call path to create, even for a create intent."""
        self._checked(resolved, task, scope)
        request = resolved.request
        if request["operation"] in ("read_text", "create_text"):
            path = request["arguments"]["path"]
            result = observe(self.paths, task["project_id"], path,
                             scope.get("create_bindings", {}).get(path))
            if request["operation"] == "create_text":
                del result["text"]
            return result
        return {"records": self.memory.search(request["arguments"]["query"],
                 project_id=task["project_id"], allowed_classes=tuple(scope["memory_classes"]))}

    def verify(self, resolved: Resolved, result: dict, task: dict, scope: dict):
        if not Draft202012Validator(resolved.descriptor["output_schema"]).is_valid(result):
            raise AgentError("invalid_tool_output")
        if resolved.request["operation"] == "create_text":
            data = resolved.request["arguments"]["text"].encode("utf-8")
            if result["bytes"] != len(data) or result["sha256"] != hashlib.sha256(data).hexdigest():
                raise AgentError("created_content_mismatch")
        if result != self.observe(resolved, task, scope):
            raise AgentError("source_changed_during_verification")
