#!/usr/bin/env python3
"""Validation of machine-readable planning contracts; requires jsonschema>=4.23."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

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


def check_refs(record: dict, field: str, allowed: set[str], errors: list[str]) -> None:
    for ref in record.get(field, []):
        if ref not in allowed:
            errors.append(f"{record.get('id')}: unknown {field} reference {ref}")


def check() -> list[str]:
    errors: list[str] = []
    manifest = load("spec/manifest.json")
    if manifest.get("schema_version") != "1.0":
        errors.append("manifest: unsupported schema_version")

    for item in manifest.get("entrypoints", []):
        if not (ROOT / item["path"]).is_file():
            errors.append(f"manifest: missing entrypoint {item['path']}")
    for path in manifest.get("references", []) + manifest.get("schemas", []):
        if not (ROOT / path).is_file():
            errors.append(f"manifest: missing referenced file {path}")
    for name in (*KINDS.keys(), "components"):
        if not (ROOT / f"spec/{name}.json").is_file():
            errors.append(f"missing spec/{name}.json")
    for source in (ROOT / "spec").rglob("*.json"):
        try:
            json.loads(source.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            errors.append(f"invalid JSON {source.relative_to(ROOT)}: {exc}")
    if errors:
        return errors

    chosen = load("spec/model-config.json")
    if chosen.get("primary_local", {}).get("model") != "qwen3.5:9b":
        errors.append("model-config: owner-selected model mismatch")
    if chosen.get("primary_local", {}).get("provider") != "ollama":
        errors.append("model-config: provider must be ollama")
    if chosen.get("selection_policy", {}).get("comparative_model_benchmarks") != "not_required":
        errors.append("model-config: comparative tests were declined")

    storage = load("spec/storage-config.json")
    if storage.get("policy_id") != "ADR-016" or storage.get("default_root") != r"G:\Assistant":
        errors.append("storage-config: wrong owner-approved default root")
    layout = storage.get("layout", {})
    required = {"repository", "models_ollama", "data", "db", "history", "memory", "identity",
                "skills", "workspace", "logs", "backups", "cache"}
    if not required.issubset(layout):
        errors.append("storage-config: missing required directory entries")
    for label, path in layout.items():
        if (not isinstance(path, str) or not path or path.startswith(("/", chr(92)))
                or ":" in path or ".." in path.replace(chr(92), "/").split("/")):
            errors.append(f"storage-config: unsafe relative directory {label}")
    if storage.get("ollama", {}).get("default_model_storage") != r"G:\Assistant\models\ollama":
        errors.append("storage-config: Ollama default path mismatch")
    if storage.get("relative_path_policy", {}).get("no_silent_fallback_to_system_disk") is not True:
        errors.append("storage-config: no-fallback invariant missing")
    if storage.get("path_resolution", {}).get("migration_change_only_app_root") is not True:
        errors.append("storage-config: single-root migration invariant missing")
    env = (ROOT / ".env.example").read_text(encoding="utf-8")
    for line in env.splitlines():
        if line.startswith("ASSISTANT_") and "_DIR=" in line:
            errors.append(".env.example: subordinate absolute directory override forbidden")
        if line.startswith("OLLAMA_MODELS="):
            errors.append(".env.example: Ollama Desktop variable must be set in its own environment")
    if "ASSISTANT_ROOT=G:" + chr(92) + "Assistant" not in env:
        errors.append(".env.example: missing owner-approved root")

    sets: dict[str, set[str]] = {}
    docs: dict[str, list[dict]] = {}
    for kind, (collection, pattern) in KINDS.items():
        records = load(f"spec/{kind}.json")[collection]
        ids = [record.get("id", "") for record in records]
        if len(set(ids)) != len(ids) or any(re.fullmatch(pattern, i) is None for i in ids):
            errors.append(f"{kind}: duplicate or invalid IDs")
        sets[kind], docs[kind] = set(ids), records

    tasks = docs["tasks"]
    coverage: dict[str, list[dict]] = {key: [] for key in sets["requirements"]}
    for task in tasks:
        check_refs(task, "requirement_ids", sets["requirements"], errors)
        check_refs(task, "depends_on", sets["tasks"], errors)
        if task.get("milestone") not in sets["milestones"]:
            errors.append(f"{task['id']}: unknown milestone")
        if task.get("status") not in ("todo", "in_progress", "blocked", "done", "cancelled"):
            errors.append(f"{task['id']}: invalid status")
        if task.get("status") == "done" and not task.get("evidence"):
            errors.append(f"{task['id']}: done without evidence")
        if not task.get("acceptance"):
            errors.append(f"{task['id']}: missing acceptance criteria")
        for ref in task.get("requirement_ids", []):
            if ref in coverage:
                coverage[ref].append(task)

    milestone_num = lambda s: int(s[1:])
    for req in docs["requirements"]:
        if req.get("target_milestone") not in sets["milestones"]:
            errors.append(f"{req['id']}: unknown milestone")
        if req.get("priority") not in ("P0", "P1", "P2"):
            errors.append(f"{req['id']}: bad priority")
        if req.get("status") not in ("proposed", "specified", "implemented", "deprecated"):
            errors.append(f"{req['id']}: bad status")
        if req.get("status") == "implemented" and not req.get("evidence"):
            errors.append(f"{req['id']}: implemented without evidence")
        if not req.get("acceptance"):
            errors.append(f"{req['id']}: missing acceptance")
        linked = coverage.get(req["id"], [])
        if req.get("status") != "deprecated" and not linked:
            errors.append(f"{req['id']}: no implementation/deferred task")
        if req.get("priority") == "P0" and not any(
            milestone_num(t["milestone"]) <= milestone_num(req["target_milestone"])
            for t in linked if t.get("milestone") in sets["milestones"]
        ):
            errors.append(f"{req['id']}: P0 not covered by target milestone")

    for cap in docs["capabilities"]:
        check_refs(cap, "requirement_ids", sets["requirements"], errors)
        if cap.get("status") not in ("planned", "in_progress", "implemented", "deprecated"):
            errors.append(f"{cap['id']}: invalid status")
        if cap.get("side_effect") not in ("read", "workspace_write", "external_send",
                                          "privileged_change", "financial"):
            errors.append(f"{cap['id']}: invalid side effect")
        if (cap.get("side_effect") in ("external_send", "privileged_change", "financial")
                and cap.get("policy") != "approval"):
            errors.append(f"{cap['id']}: dangerous action must require approval")
    github_read = next((x for x in docs["capabilities"] if x["id"] == "CAP-022"), {})
    github_write = next((x for x in docs["capabilities"] if x["id"] == "CAP-028"), {})
    if (github_read.get("side_effect") != "read" or github_read.get("policy") != "scoped"
            or github_write.get("policy") != "approval"
            or github_write.get("side_effect") != "external_send"):
        errors.append("GitHub read/write operations must have different trust policies")

    for scenario in docs["scenarios"]:
        check_refs(scenario, "requirement_ids", sets["requirements"], errors)
        check_refs(scenario, "capability_ids", sets["capabilities"], errors)
        if scenario.get("target_milestone") not in sets["milestones"] or not scenario.get("acceptance"):
            errors.append(f"{scenario['id']}: missing acceptance/milestone")

    for dec in docs["decisions"]:
        if dec.get("status") not in ("proposed", "provisional", "accepted", "rejected", "superseded", "open"):
            errors.append(f"{dec['id']}: invalid decision status")
    for adr in ("ADR-001", "ADR-002", "ADR-003", "ADR-004", "ADR-005", "ADR-006",
                "ADR-007", "ADR-012", "ADR-014", "ADR-015", "ADR-016", "ADR-017",
                "ADR-018", "ADR-019", "ADR-020"):
        if not any(x["id"] == adr and x["status"] == "accepted" for x in docs["decisions"]):
            errors.append(f"{adr}: M1 baseline decision is not accepted")

    graph = {t["id"]: t.get("depends_on", []) for t in tasks}
    task_statuses = {t["id"]: t["status"] for t in tasks}
    for task in tasks:
        if task["status"] == "done" and any(task_statuses.get(dep) != "done"
                                           for dep in task.get("depends_on", [])):
            errors.append(f"{task['id']}: done before dependency gate")
    visited: set[str] = set()
    visiting: set[str] = set()
    def visit(node: str) -> None:
        if node in visiting:
            errors.append(f"task dependency cycle at {node}")
            return
        if node in visited or node not in graph:
            return
        visiting.add(node)
        for other in graph[node]:
            visit(other)
        visiting.remove(node)
        visited.add(node)
    for node in graph:
        visit(node)

    components = load("spec/components.json")["components"]
    if len({c["id"] for c in components}) != len(components):
        errors.append("components: duplicate IDs")

    for path in manifest.get("schemas", []):
        schema = load(path)
        if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
            errors.append(f"{path}: invalid JSON Schema dialect")
            continue
        try:
            Draft202012Validator.check_schema(schema)
        except Exception as exc:
            errors.append(f"{path}: invalid JSON Schema definition: {exc}")
            continue
        key = Path(path).name.removesuffix(".schema.json")
        fixture = ROOT / "spec" / "examples" / (key + ".json")
        if not fixture.is_file():
            errors.append(f"{path}: missing example {fixture.name}")
            continue
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        for exc in validator.iter_errors(load(f"spec/examples/{key}.json")):
            errors.append(f"{key}: invalid fixture: {exc.message}")
    return errors


if __name__ == "__main__":
    problems = check()
    if problems:
        for problem in problems:
            print("ERROR:", problem, file=sys.stderr)
        raise SystemExit(1)
    print("PASS: JSON Schema fixtures, IDs, coverage, DAG, approvals, model/storage and docs")
