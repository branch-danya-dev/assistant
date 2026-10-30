"""Owner-only local CLI. No unauthenticated web service or remote approval interface."""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys

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
    run.add_argument("--include-private", action="store_true", help="Explicit local-only private memory scope")
    for command in ("show", "resume", "cancel"):
        commands.add_parser(command).add_argument("task_id")
    approval = commands.add_parser("approve")
    approval.add_argument("approval_id")
    approval.add_argument("--digest", required=True, help="Digest from the reviewed exact action")
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
        if args.command in ("stop", "clear-stop"):
            journal.stop(args.command == "stop")
            return {"stopped": journal.stopped(), "in_flight_effects_undone": False}
        if args.command == "run":
            paths.project_workspace(args.project)
            scope = {"files": [safe_relative(p) for p in args.allow_file], "memory_classes":
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
            if args.command == "recover":
                return {"recovered_task_ids": journal.recover(), "executed_actions": 0}
            if args.command == "cancel":
                journal.recover()
                journal.transition(args.task_id, "cancelled")
                return journal.inspect(args.task_id)
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
        print(json.dumps(result, ensure_ascii=False, indent=2))
        state = result.get("task", {}).get("state")
        return 0 if state in (None, "completed", "cancelled") else 2
    except (AgentError, OSError, sqlite3.Error) as exc:
        code = str(exc) if isinstance(exc, AgentError) else "local_storage_or_permission_error"
        print(json.dumps({"error": code}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
