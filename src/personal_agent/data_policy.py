"""M1 data admission, not a universal secret detector or an OS sandbox.

Owner scope classifies whole files. Memory labels are checked before retrieval and
again before IPC/model projection. Content can never grant itself a lower class.
Recognizable credentials are denied as defence in depth, without echoing payloads.
"""
from __future__ import annotations

import json
import re

from .config import AgentError, safe_relative

CLASSES = frozenset({"public", "internal", "private", "restricted"})
SECRET_KEYS = frozenset({"password", "passwd", "secret", "token", "api_key", "apikey",
                         "authorization", "access_token", "refresh_token", "private_key"})
SECRET_TEXT = re.compile(
    r"-----BEGIN [^-]*PRIVATE KEY-----|\b(?:sk-|gh[pousr]_)[A-Za-z0-9_-]{12,}|"
    r"\b(?:password|passwd|secret|token|api[_-]?key|authorization)\b\s*[:=]\s*\S+",
    re.I,
)


def admit(value, *, depth=0):
    """Reject known credential shapes before persistence, IPC or model admission.

    No substitution/truncation: a denied object is rejected in its entirety.
    Nested JSON strings are inspected too. Unlabelled arbitrary prose is NOT
    proven secret-free; REQ-019 stays open for that explicit residual risk.
    """
    if depth > 24:
        raise AgentError("data_nesting_denied")
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise AgentError("invalid_data_object")
            if key.lower().replace("-", "_") in SECRET_KEYS:
                raise AgentError("credential_content_denied")
            admit(key, depth=depth + 1)
            admit(item, depth=depth + 1)
    elif isinstance(value, (list, tuple)):
        for item in value:
            admit(item, depth=depth + 1)
    elif isinstance(value, str):
        if SECRET_TEXT.search(value):
            raise AgentError("credential_content_denied")
        if value.lstrip().startswith(("{", "[", '"')):
            try:
                parsed = json.loads(value)
            except (ValueError, RecursionError):
                parsed = None
            if parsed is not None and parsed != value:
                admit(parsed, depth=depth + 1)


def validate_scope(scope):
    if (not isinstance(scope, dict) or not set(scope) <= {
            "files", "create_files", "create_bindings", "memory_classes",
            "file_classes", "private_files"}):
        raise AgentError("invalid_data_scope")
    for key in ("files", "create_files", "private_files"):
        if not isinstance(scope.get(key, []), list):
            raise AgentError("invalid_data_scope")
        for path in scope.get(key, []):
            if safe_relative(path) != path:
                raise AgentError("invalid_data_scope")
    classes = scope.get("memory_classes", [])
    if not isinstance(classes, list) or any(c not in CLASSES - {"restricted"} for c in classes):
        raise AgentError("memory_sensitivity_denied")
    labels = scope.get("file_classes", {})
    if (not isinstance(labels, dict) or not set(labels) <= set(scope.get("files", []))
            or any(c not in CLASSES for c in labels.values())
            or not set(scope.get("private_files", [])) <= set(scope.get("files", []))):
        raise AgentError("invalid_data_scope")
    admit(scope)


def file_access(path, scope):
    # Legacy exact allow-file is an owner grant of internal local context. The
    # caller must not use it for secrets; migrations never relabel stored sources.
    classification = scope.get("file_classes", {}).get(path, "internal")
    if classification == "restricted" or classification not in CLASSES:
        raise AgentError("file_sensitivity_denied")
    if classification == "private" and path not in scope.get("private_files", []):
        raise AgentError("file_sensitivity_denied")


def tool_result(request, result, task, scope):
    """Recheck actual returned data, including provenance, before crossing a sink."""
    operation = request["operation"]
    if operation == "read_text":
        file_access(request["arguments"]["path"], scope)
    elif operation == "search_memory":
        for record in result.get("records", []):
            if (record.get("project_id") != task["project_id"]
                    or record.get("sensitivity") not in scope.get("memory_classes", [])
                    or record.get("sensitivity") == "restricted"):
                raise AgentError("memory_sensitivity_denied")
    admit(result)


def external_source(source_kind, content):
    """Contract for future connectors: no adapter is admitted at M1."""
    raise AgentError("external_source_not_enabled")
