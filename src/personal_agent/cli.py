"""Owner-only local CLI. No unauthenticated web service or remote approval interface."""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

from .config import AgentError, Paths, safe_relative
from .demo import run_demo
from .identity import Identity
from .journal import Journal
from .memory import Memory
from .models import Ollama
from .orchestrator import Agent
from .storage import Store


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Local personal agent (partial M1)")
    root.add_argument("--root", help="Explicit ASSISTANT_ROOT override; default G:\\Assistant on Windows")
    commands = root.add_subparsers(dest="command", required=True)
    for command in ("init", "doctor", "smoke", "demo", "tasks", "stop", "clear-stop", "recover", "backup", "persona"):
        commands.add_parser(command)
    run = commands.add_parser("run")
    run.add_argument("intent")
    run.add_argument("--project", required=True)
    run.add_argument("--allow-file", action="append", default=[], help="Exact project-workspace relative UTF-8 file")
    run.add_argument("--allow-create", action="append", default=[],
                     help="Exact NEW file in existing project directories; separate approval is still required")
    run.add_argument("--include-private", action="store_true", help="Explicit local-only private memory scope")
    for command in ("show", "resume", "cancel"):
        commands.add_parser(command).add_argument("task_id")
    evidence = commands.add_parser("show-evidence")
    evidence.add_argument("task_id")
    evidence.add_argument("evidence_ref")
    evidence.add_argument("--project", required=True)
    evidence.add_argument("--limit", type=int, default=16384)
    revise = commands.add_parser("revise")
    revise.add_argument("task_id")
    revise.add_argument("--plan", type=Path, required=True,
                        help="JSON proposal with base_digest, reason and immutable step identities")
    approval = commands.add_parser("approve")
    approval.add_argument("approval_id")
    approval.add_argument("--digest", required=True, help="Digest from the reviewed exact action")
    preview = commands.add_parser("approval-preview")
    preview.add_argument("approval_id")
    preview.add_argument("--project", required=True)
    reconcile = commands.add_parser("reconcile")
    reconcile.add_argument("action_id")
    reconcile.add_argument("--outcome", required=True, choices=("applied", "not_applied"))
    reconcile.add_argument("--evidence", required=True)
    memory = commands.add_parser("memory").add_subparsers(dest="memory_command", required=True)
    add = memory.add_parser("add")
    add.add_argument("statement")
    add.add_argument("--project", required=True)
    add.add_argument("--source", required=True)
    add.add_argument("--sensitivity", choices=("public", "internal", "private", "restricted"), default="private")
    add.add_argument("--supersedes", action="append", default=[])
    search = memory.add_parser("search")
    search.add_argument("query")
    search.add_argument("--project", required=True)
    search.add_argument("--include-private", action="store_true")
    remove = memory.add_parser("remove")
    remove.add_argument("record_id")
    remove.add_argument("--project", required=True)
    memory.add_parser("reindex")
    return root


def model_storage_status(paths: Paths) -> dict:
    value = None
    if os.name == "nt":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
                value = winreg.QueryValueEx(key, "OLLAMA_MODELS")[0]
        except FileNotFoundError:
            pass
    expected = str(paths.directory("models_ollama"))
    return {"expected": expected, "windows_user_value_matches":
            os.path.normcase(value or "") == os.path.normcase(expected),
            "running_process_environment_verified": False,
            "note": "Ollama Desktop must be restarted after its User environment changes; .env is not applied."}


def execute(args) -> dict:
    paths = Paths(args.root)
    if args.command == "doctor":
        result = {"root": str(paths.root), "initialized": paths.directory("db").is_dir(),
                  "model_storage": model_storage_status(paths)}
        try:
            result["ollama"] = Ollama(timeout=3).status()
        except AgentError as exc:
            result["ollama"] = {"reachable": False, "error": str(exc)}
        return result
    if args.command == "smoke":
        if os.name == "nt" and not model_storage_status(paths)["windows_user_value_matches"]:
            raise AgentError("ollama_user_model_storage_not_configured")
        return Ollama().smoke()
    if args.command == "demo":
        return run_demo(paths)
    if args.command == "init":
        paths.bootstrap()
        with Store(paths) as store, store.execution_lock():
            Identity(paths).initialize()
        return {"initialized": True, "root": str(paths.root),
                "model_storage": model_storage_status(paths)}
    with Store(paths) as store:
        journal, memory = Journal(store), Memory(store)
        if args.command == "tasks":
            return {"tasks": [{"task_id": row[0], "state": row[1]} for row in
                              store.connection.execute("SELECT id,state FROM tasks ORDER BY rowid DESC LIMIT 100")]}
        if args.command == "show":
            return journal.inspect(args.task_id)
        if args.command == "show-evidence":
            if not 256 <= args.limit <= 32768:
                raise AgentError("invalid_output_limit")
            result = journal.evidence(args.task_id, args.evidence_ref, args.project)
            if len(json.dumps(result).encode()) > args.limit:
                return {"evidence_ref": args.evidence_ref, "truncated": True,
                        "result_digest": result["result_digest"], "output_limit": args.limit}
            return result
        if args.command in ("stop", "clear-stop"):
            journal.stop(args.command == "stop")
            return {"stopped": journal.stopped(), "in_flight_effects_undone": False}
        if args.command == "cancel":
            journal.cancel(args.task_id)
            return journal.inspect(args.task_id)
        if args.command == "run":
            paths.project_workspace(args.project)
            scope = {"files": [safe_relative(p) for p in args.allow_file],
                     "create_files": [safe_relative(p) for p in args.allow_create], "memory_classes":
                     ["public", "internal", *(["private"] if args.include_private else [])]}
            task_id = journal.create(args.intent, args.project, scope)
            return Agent(store, Ollama()).run(task_id)
        if args.command == "resume":
            return Agent(store, Ollama()).run(args.task_id, resume=True)
        if args.command == "backup":
            return {"database_backup": store.backup(), "note": "Copy identity and other data separately while stopped."}
        if args.command == "persona":
            return Identity(paths).current()
        with store.execution_lock():
            if args.command == "approval-preview":
                approval = journal.approval(args.approval_id)
                task_id = approval["task_id"]
                if journal.get(task_id)["project_id"] != args.project:
                    raise AgentError("approval_scope_mismatch")
                action_row = store.connection.execute("SELECT action_id FROM approvals WHERE id=?",
                                                       (args.approval_id,)).fetchone()
                action = journal.action(action_row[0])
                # Owner-requested private review artifact: full proposed bytes stay out of stdout.
                document = {"approval": approval, "request": json.loads(action["request"]),
                            "scope": journal.scope(task_id), "action_id": action["id"]}
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", prefix="approval-",
                                                  suffix=".json", dir=paths.directory("cache"),
                                                  delete=False) as file:
                    json.dump(document, file, ensure_ascii=False, indent=2)
                    preview_path = Path(file.name).relative_to(paths.root).as_posix()
                return {"approval_id": args.approval_id, "arguments_digest": action["digest"],
                        "private_preview_relative": preview_path, "status": approval["status"]}
            if args.command == "revise":
                journal.recover()
                with args.plan.open("rb") as file:
                    raw = file.read(65537)
                if len(raw) > 65536:
                    raise AgentError("plan_input_budget_exhausted")
                try:
                    proposal = json.loads(raw)
                except ValueError as exc:
                    raise AgentError("invalid_plan_revision") from exc
                journal.plans.revise(args.task_id, proposal, Agent(store, Ollama()).registry)
                return journal.inspect(args.task_id)
            if args.command == "recover":
                return {"recovered_task_ids": journal.recover(), "executed_actions": 0}
            if args.command == "approve":
                journal.approve(args.approval_id, args.digest)
                return journal.approval(args.approval_id)
            if args.command == "reconcile":
                journal.reconcile(args.action_id, args.outcome, args.evidence)
                return {"reconciled": True, "automatic_replay": False}
            if args.command == "memory":
                if args.memory_command == "add":
                    return {"record_id": memory.remember(args.project, args.statement, args.source,
                             sensitivity=args.sensitivity, supersedes=args.supersedes)}
                if args.memory_command == "search":
                    classes = ("public", "internal", "private") if args.include_private else ("public", "internal")
                    return {"records": memory.search(args.query, project_id=args.project, allowed_classes=classes)}
                if args.memory_command == "remove":
                    memory.remove_from_retrieval(args.record_id, project_id=args.project)
                    return {"removed_from_retrieval": True, "physical_and_backup_erasure": False}
                memory.rebuild_index()
                return {"index_rebuilt": True}
        raise AgentError("unsupported_command")


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        result = execute(parser().parse_args(argv))
        rendered = json.dumps(result, ensure_ascii=False, indent=2)
        if len(rendered.encode("utf-8")) > 65536:
            # Source metadata can still be large. Keep the state readable, and make truncation explicit.
            rendered = json.dumps({"task_id": result.get("task", {}).get("task_id"),
                "state": result.get("task", {}).get("state"), "truncated": True,
                "preview": rendered.encode("utf-8")[:16000].decode("utf-8", errors="ignore")},
                ensure_ascii=False, indent=2)
        print(rendered)
        state = result.get("task", {}).get("state")
        return 0 if state in (None, "completed", "cancelled") else 2
    except (AgentError, OSError, sqlite3.Error) as exc:
        code = str(exc) if isinstance(exc, AgentError) else "local_storage_or_permission_error"
        print(json.dumps({"error": code}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
