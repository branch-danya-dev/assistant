"""Fail-closed replacement for the external 2026-10-31 installed_acceptance.py.

Use an installed wheel from outside its checkout and an explicitly fresh test root.
No model download, production database, credential or host-configuration access.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from personal_agent.config import Paths
from personal_agent.identity import Identity
from personal_agent.journal import Journal
from personal_agent.memory import Memory
from personal_agent.models import Ollama
from personal_agent.orchestrator import Agent
from personal_agent.storage import Store


def stage(name, root, endpoint):
    model = Ollama(endpoint=endpoint)
    if name == "smoke":
        result = model.smoke()
        checks = {"reachable": result.get("reachable") is True,
                  "installed": result.get("installed") is True,
                  "text": result.get("text_generation") == "pass",
                  "intent": result.get("structured_tool_intent") == "pass"}
    else:
        paths = Paths(root)
        if paths.root.exists():
            raise ValueError("fresh_root_required")
        paths.bootstrap()
        workspace = paths.project_workspace("acceptance")
        workspace.mkdir()
        (workspace / "note.txt").write_text("Synthetic reference BIRCH583.", encoding="utf-8")
        with Store(paths) as store:
            Identity(paths).initialize()
            memory = Memory(store)
            memory.remember("acceptance", "Invoice MAPLE417", "fixture://owner", sensitivity="internal")
            expired = memory.remember("acceptance", "MAPLE417 CANARY_EXPIRED_921",
                                      "fixture://expired", sensitivity="internal")
            store.connection.execute("UPDATE data_admissions SET expires_at='2000-01-01T00:00:00Z'"
                                     " WHERE object_id=?", (expired,))
            journal = Journal(store)
            task = journal.create("Read note.txt and search memory for MAPLE417. Report both reference "
                "codes with both action evidence refs. No revision needed.", "acceptance",
                {"files": ["note.txt"], "memory_classes": ["internal"]},
                budget={"model_limit": 2, "tool_limit": 2, "wall_seconds": 180})
            result = Agent(store, model).run(task)
            answer = (result.get("result") or {}).get("answer", "")
            checks = {"completed": result["task"]["state"] == "completed",
                "answer": "BIRCH583" in answer and "MAPLE417" in answer,
                "tools": {a["request"]["operation"] for a in result["actions"]
                          if a["status"] == "verified"} == {"read_text", "search_memory"},
                "once": len(result["actions"]) == 2 and all(a["attempts"] == 1 for a in result["actions"]),
                "canary_absent": "CANARY_EXPIRED_921" not in json.dumps(result),
                "no_approval": store.connection.execute("SELECT count(*) FROM approvals").fetchone()[0] == 0}
    passed = bool(checks) and all(v is True for v in checks.values())
    return {"stage": name, "checks": checks, "passed": passed,
            "status": "PASSED" if passed else "FAILED"}


def run_gates(root, endpoint=None, *, runner=subprocess.run):
    reports = {}
    for name in ("smoke", "workflow"):
        command = [sys.executable, str(Path(__file__).resolve()), "--stage", name,
                   "--root", str(root)]
        if endpoint:
            command += ["--endpoint", endpoint]
        try:
            child = runner(command, capture_output=True, text=True, encoding="utf-8", timeout=240)
            payload = json.loads(child.stdout)
            passed = (child.returncode == 0 and payload.get("passed") is True
                      and payload.get("status") == "PASSED" and payload.get("stage") == name
                      and bool(payload.get("checks"))
                      and all(v is True for v in payload["checks"].values()))
            reports[name] = {"exit_code": child.returncode, "passed": passed,
                             "status": "PASSED" if passed else "FAILED"}
        except Exception:
            # Never echo model output, exception messages, paths or child stderr.
            reports[name] = {"passed": False, "status": "FAILED", "error": "gate_process_failed"}
    passed = all(r["passed"] for r in reports.values())
    return {"passed": passed, "status": "PASSED" if passed else "FAILED", "gates": reports}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--endpoint", help="Numeric loopback only; optional local test stub")
    parser.add_argument("--stage", choices=("smoke", "workflow"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        report = stage(args.stage, args.root, args.endpoint) if args.stage else run_gates(args.root, args.endpoint)
    except Exception:
        report = {"stage": args.stage, "passed": False, "status": "FAILED", "error": "live_gate_failed"}
    rendered = json.dumps(report, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["passed"] is True else 2


if __name__ == "__main__":
    raise SystemExit(main())
