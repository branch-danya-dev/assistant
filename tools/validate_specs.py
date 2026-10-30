#!/usr/bin/env python3
"""Dependency-free validator for the agent-first planning repository."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KINDS = {
    "requirements": ("requirements", r"REQ-\d{3}"),
    "capabilities": ("capabilities", r"CAP-\d{3}"),
    "scenarios": ("scenarios", r"SCN-\d{3}"),
    "decisions": ("decisions", r"ADR-\d{3}"),
    "tasks": ("tasks", r"TASK-\d{3}"),
    "milestones": ("milestones", r"M\d+"),
}


def load(relative: str) -> dict:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def check() -> list[str]:
    errors: list[str] = []
    manifest = load("spec/manifest.json")
    if manifest.get("schema_version") != "1.0":
        errors.append("manifest: unsupported schema_version")
    storage = load("spec/storage-config.json")
    if storage.get("policy_id") != "ADR-016" or storage.get("default_root") != "G:\\Assistant":
        errors.append("storage-config: owner-approved G: root mismatch")
    layout = storage.get("layout", {})
    required = {"repository", "models_ollama", "data", "db", "history", "memory", "identity", "skills", "workspace", "logs", "backups", "cache"}
    if not required.issubset(layout):
        errors.append("storage-config: missing directories")
    for label, path in layout.items():
        if (not isinstance(path, str) or not path or path.startswith(("/", "\\\\")) or
                ":" in path or ".." in path.replace("\\\\", "/").split("/")):
            errors.append(f"storage-config: unsafe relative directory {label}")
    if storage.get("ollama", {}).get("default_model_storage") != "G:\\Assistant\\models\\ollama":
        errors.append("storage-config: Ollama storage mismatch")
    if storage.get("relative_path_policy", {}).get("no_silent_fallback_to_system_disk") is not True:
        errors.append("storage-config: no fallback policy missing")
    selected = load("spec/model-config.json")
    if selected.get("primary_local", {}).get("model") != "qwen3.5:9b":
        errors.append("model-config: primary local model differs from ADR-015")
    if selected.get("primary_local", {}).get("provider") != "ollama":
        errors.append("model-config: primary provider must be ollama")
    if selected.get("selection_policy", {}).get("comparative_model_benchmarks") != "not_required":
        errors.append("model-config: owner declined comparative model benchmarks")
    for doc in manifest.get("entrypoints", []):
        if not (ROOT / doc["path"]).is_file():
            errors.append(f"manifest: missing entrypoint {doc['path']}")
    for ref in manifest.get("references", []):
        if not (ROOT / ref).is_file():
            errors.append(f"manifest: missing reference {ref}")
    for name in ("requirements", "capabilities", "scenarios", "decisions", "tasks", "milestones", "components"):
        if not (ROOT / f"spec/{name}.json").is_file():
            errors.append(f"missing spec/{name}.json")
    for source in sorted((ROOT / "spec").rglob("*.json")):
        try:
            json.loads(source.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            errors.append(f"invalid JSON {source.relative_to(ROOT)}: {e}")
    if errors:
        return errors

    sets: dict[str, set[str]] = {}
    docs: dict[str, list[dict]] = {}
    for kind, (collection, pattern) in KINDS.items():
        doc = load(f"spec/{kind}.json")
        records = doc[collection]
        ids = [r.get("id", "") for r in records]
        if any(not re.fullmatch(pattern, item) for item in ids):
            errors.append(f"{kind}: invalid identifier")
        if len(ids) != len(set(ids)):
            errors.append(f"{kind}: duplicate IDs")
        sets[kind] = set(ids)
        docs[kind] = records

    for r in docs["requirements"]:
        if r.get("priority") not in ("P0", "P1", "P2"):
            errors.append(f"{r['id']}: invalid priority")
        if r.get("target_milestone") not in sets["milestones"]:
            errors.append(f"{r['id']}: unknown milestone")
        if r.get("status") not in ("proposed", "specified", "implemented", "deprecated"):
            errors.append(f"{r['id']}: invalid status")
        if not r.get("acceptance"):
            errors.append(f"{r['id']}: no acceptance")

    for c in docs["capabilities"]:
        check_refs(c, "requirement_ids", sets["requirements"], errors)
        if c.get("status") not in ("planned", "in_progress", "implemented", "deprecated"):
            errors.append(f"{c['id']}: bad status")
        if c.get("side_effect") not in ("read", "workspace_write", "external_send", "privileged_change", "financial"):
            errors.append(f"{c['id']}: bad side effect")
        if c["side_effect"] in ("external_send", "privileged_change", "financial") and c.get("policy") != "approval":
            errors.append(f"{c['id']}: sensitive action must require approval")

    for s in docs["scenarios"]:
        check_refs(s, "requirement_ids", sets["requirements"], errors)
        check_refs(s, "capability_ids", sets["capabilities"], errors)
        if s.get("target_milestone") not in sets["milestones"]:
            errors.append(f"{s['id']}: unknown milestone")
        if not s.get("acceptance"):
            errors.append(f"{s['id']}: missing acceptance")

    for d in docs["decisions"]:
        if d.get("status") not in ("proposed", "provisional", "accepted", "rejected", "superseded", "open"):
            errors.append(f"{d['id']}: invalid status")

    graphs: dict[str, list[str]] = {}
    for task in docs["tasks"]:
        check_refs(task, "requirement_ids", sets["requirements"], errors)
        check_refs(task, "depends_on", sets["tasks"], errors)
        if task.get("milestone") not in sets["milestones"]:
            errors.append(f"{task['id']}: unknown milestone")
        if task.get("status") not in ("todo", "in_progress", "blocked", "done", "cancelled"):
            errors.append(f"{task['id']}: invalid status")
        if task.get("status") == "done" and not task.get("evidence"):
            errors.append(f"{task['id']}: done without evidence")
        if not task.get("acceptance"):
            errors.append(f"{task['id']}: missing acceptance")
        graphs[task["id"]] = task.get("depends_on", [])
    done: set[str] = set()
    visiting: set[str] = set()

    def visit(node: str) -> None:
        if node in visiting:
            errors.append(f"task dependency cycle at {node}")
            return
        if node in done or node not in graphs:
            return
        visiting.add(node)
        for other in graphs[node]:
            visit(other)
        visiting.remove(node)
        done.add(node)

    for node in graphs:
        visit(node)

    component_ids = [r["id"] for r in load("spec/components.json")["components"]]
    if len(component_ids) != len(set(component_ids)):
        errors.append("components: duplicate IDs")

    for path in manifest.get("schemas", []):
        schema = load(path)
        if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
            errors.append(f"{path}: bad JSON schema dialect")
        if schema.get("type") != "object" or not schema.get("required"):
            errors.append(f"{path}: missing basic contract")

    return errors


def check_refs(obj: dict, field: str, allowed: set[str], errors: list[str]) -> None:
    for ref in obj.get(field, []):
        if ref not in allowed:
            errors.append(f"{obj.get('id')}: unknown {field} reference {ref}")


if __name__ == "__main__":
    problems = check()
    if problems:
        for problem in problems:
            print("ERROR:", problem, file=sys.stderr)
        raise SystemExit(1)
    print("PASS: JSON, IDs, references, DAG, approvals, docs, schema headers")
