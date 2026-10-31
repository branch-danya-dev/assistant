"""Owner-only local CLI. No unauthenticated web service or remote approval interface."""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

from .config import AgentError, Paths, safe_relative
from .data_policy import admit
from .demo import run_demo
from .identity import Identity
from .journal import Journal
from .memory import Memory
from .models import Ollama
from .orchestrator import Agent
from .previews import Previews
from .storage import Store
from .trust import Trust


class OwnerParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse's default diagnostic embeds unknown arguments/choice values.
        raise AgentError("invalid_cli_arguments")


def parser() -> argparse.ArgumentParser:
    root = OwnerParser(description="Local personal agent (M1)")
    root.add_argument("--root", help="Explicit ASSISTANT_ROOT override; default G:\\Assistant on Windows")
    commands = root.add_subparsers(dest="command", required=True)
    audit = commands.add_parser("data-audit", help="IDs, labels and review digests only; no contents")
    audit.add_argument("--project", required=True)
    for command in ("data-review", "data-renew"):
        review = commands.add_parser(command, help="Owner attestation by exact ID/project/digest/label")
        review.add_argument("kind", choices=("task", "memory", "persona"))
        review.add_argument("id")
        review.add_argument("--project", required=True)
        review.add_argument("--digest", required=True)
        review.add_argument("--classification", required=True, choices=("public", "internal", "private"))
        review.add_argument("--expires-at", required=True)
    inventory = commands.add_parser("inventory-mark", help="Register source metadata only; never read content")
    inventory.add_argument("kind", choices=("file", "task", "memory", "persona", "preview"))
    inventory.add_argument("locator")
    inventory.add_argument("--project", required=True)
    inventory.add_argument("--classification", default="restricted",
                           choices=("public", "internal", "private", "restricted", "unclassified"))
    inventory.add_argument("--expires-at", required=True)
    reviewed = commands.add_parser("inventory-review", help="Review a metadata mark; grants no tool permission")
    reviewed.add_argument("id")
    reviewed.add_argument("--classification", required=True,
                          choices=("public", "internal", "private", "restricted"))
    reviewed.add_argument("--expires-at", required=True)
    commands.add_parser("cleanup-previews", help="Remove expired registered approval previews only")
    for command in ("init", "doctor", "smoke", "demo", "tasks", "stop", "clear-stop", "recover", "backup", "persona"):
        commands.add_parser(command)
    run = commands.add_parser("run")
    run.add_argument("intent")
    run.add_argument("--private-intent", action="store_true",
                     help="Attest task intent as private-local; diagnostics withhold its content")
    run.add_argument("--project", required=True)
    run.add_argument("--allow-file", action="append", default=[], help="Exact project-workspace relative UTF-8 file")
    run.add_argument("--allow-create", action="append", default=[],
                     help="Exact NEW file in existing project directories; separate approval is still required")
    run.add_argument("--include-private", action="store_true", help="Explicit local-only private memory scope")
    run.add_argument("--allow-private-file", action="append", default=[],
                     help="Exact private file authorized for local tool IPC and Ollama context")
    for command in ("show", "resume", "cancel"):
        commands.add_parser(command).add_argument("task_id")
    historical = commands.add_parser("show-audit", help="Payload-free task history, including expired tasks")
    historical.add_argument("task_id")
    historical.add_argument("--project", required=True)
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
    reconcile.add_argument("--project", required=True)
    reconcile.add_argument("--digest", required=True, help="Reviewed current task digest from data-audit")
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
        if args.command == "data-audit":
            return Trust(store).audit(args.project)
        if args.command == "tasks":
            return {"tasks": [{"task_id": row[0], "state": row[1]} for row in
                              store.connection.execute("SELECT id,state FROM tasks ORDER BY rowid DESC LIMIT 100")]}
        if args.command == "show":
            return journal.inspect(args.task_id)
        if args.command == "show-audit":
            return journal.historical_audit(args.task_id, args.project)
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
            private_files = [safe_relative(p) for p in args.allow_private_file]
            scope = {"files": [safe_relative(p) for p in args.allow_file] + private_files,
                     "intent_class": "private" if args.private_intent else "internal",
                     "file_classes": {p: "private" for p in private_files},
                     "private_files": private_files,
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
            if args.command == "inventory-mark":
                return {"inventory_id": Trust(store).mark(args.kind, args.project, args.locator,
                        args.classification, expires_at=args.expires_at), "content_read": False}
            if args.command == "inventory-review":
                Trust(store).review_mark(args.id, args.classification, expires_at=args.expires_at)
                return {"inventory_id": args.id, "reviewed": True, "tool_permission_granted": False}
            if args.command in ("data-review", "data-renew"):
                trust = Trust(store)
                operation = trust.renew if args.command == "data-renew" else trust.review
                operation(args.kind, args.id, args.project, args.digest,
                          args.classification, expires_at=args.expires_at)
                return {"id": args.id, "reviewed": True, "authority_changed": False,
                        "effect_approval_granted": False, "executed_actions": 0}
            if args.command == "cleanup-previews":
                return Previews(store).cleanup()
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
                preview = Previews(store).create(document)
                return {"approval_id": args.approval_id, "arguments_digest": action["digest"],
                        **preview, "status": approval["status"]}
            if args.command == "revise":
                journal.recover()
                with args.plan.open("rb") as file:
                    raw = file.read(65537)
                if len(raw) > 65536:
                    raise AgentError("plan_input_budget_exhausted")
                try:
                    proposal = json.loads(raw)
                except ValueError:
                    raise AgentError("invalid_plan_revision") from None
                journal.plans.revise(args.task_id, proposal, Agent(store, Ollama()).registry)
                return journal.inspect(args.task_id)
            if args.command == "recover":
                return {"recovered_task_ids": journal.recover(), "executed_actions": 0}
            if args.command == "approve":
                journal.approve(args.approval_id, args.digest)
                return journal.approval(args.approval_id)
            if args.command == "reconcile":
                journal.reconcile(args.action_id, args.outcome, args.evidence,
                                  project=args.project, expected_digest=args.digest)
                return {"reconciled": True, "automatic_replay": False}
            if args.command == "memory":
                if args.memory_command == "add":
                    return {"record_id": memory.remember(args.project, args.statement, args.source,
                             sensitivity=args.sensitivity, supersedes=args.supersedes)}
                if args.memory_command == "search":
                    classes = ("public", "internal", "private") if args.include_private else ("public", "internal")
                    records = memory.search(args.query, project_id=args.project, allowed_classes=classes)
                    return {"records": [{"id": r["id"], "sensitivity": r["sensitivity"],
                            "content": "[private record withheld from diagnostics]"}
                            if r["sensitivity"] == "private" else r for r in records]}
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
        admit(result)
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
