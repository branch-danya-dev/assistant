"""Public evidence projections. Free-form source text is never printed by this view."""
from __future__ import annotations

import hashlib
import re

from .config import AgentError


def redact(text: str, limit: int = 2000) -> str:
    # Defence in depth for owner/model prose, not a claim of universal secret detection.
    text = re.sub(r"-----BEGIN [^-]*PRIVATE KEY-----.*?(?:-----END [^-]*PRIVATE KEY-----|$)",
                  "[REDACTED KEY]", text, flags=re.S)
    text = re.sub(r"(?i)\b(password|passwd|secret|token|api[_-]?key|authorization)\b"
                  r"\s*[:=]\s*[^\s,;]+", r"\1=[REDACTED]", text)
    text = re.sub(r"\b(?:sk-|gh[pousr]_)[A-Za-z0-9_-]{12,}", "[REDACTED TOKEN]", text)
    text = "".join(c if c in "\n\t" or ord(c) >= 32 else "�" for c in text)
    return text[:limit] + ("…[truncated]" if len(text) > limit else "")


def text_receipt(text: str) -> dict:
    data = text.encode("utf-8")
    return {"content": "[source content withheld]", "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest()}


def project_result(request: dict, result: dict, project: str, scope: dict) -> dict:
    """Allowlist structure, never recursively dump arbitrary saved tool output."""
    operation = request["operation"]
    if operation in ("read_text", "create_text"):
        path = request["arguments"]["path"]
        key = "files" if operation == "read_text" else "create_files"
        if path not in scope.get(key, []) or result.get("path") != path:
            raise AgentError("evidence_scope_mismatch")
        return {"path": redact(path, 500), "bytes": result["bytes"],
                "sha256": result["sha256"], "content": "[source content withheld]",
                **({"identity": result["identity"]} if "identity" in result else {})}
    if operation == "search_memory":
        records = []
        for record in result.get("records", [])[:20]:
            if (record.get("project_id") != project
                    or record.get("sensitivity") not in scope.get("memory_classes", [])):
                raise AgentError("evidence_scope_mismatch")
            # Provenance strings and statements can themselves contain secrets.
            records.append({"id": record["id"], "sensitivity": record["sensitivity"],
                            **text_receipt(record["statement"])})
        return {"records": records, "count": len(records)}
    raise AgentError("evidence_operation_unsupported")
