"""Opt-in live Qwen acceptance using synthetic data only; never download/switch a model."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from personal_agent.cli import model_storage_status
from personal_agent.config import Paths
from personal_agent.identity import Identity
from personal_agent.journal import Journal
from personal_agent.memory import Memory
from personal_agent.models import Ollama
from personal_agent.orchestrator import Agent
from personal_agent.storage import Store, now, uid


def verify(root: str) -> dict:
    paths = Paths(root)
    paths.bootstrap()
    model = Ollama(timeout=120)
    smoke = model.smoke()
    info = model._request("/api/show", {"model": "qwen3.5:9b"})
    model_files = [Path(line[5:].strip().strip('"')) for line in info.get("modelfile", "").splitlines()
                   if line.startswith("FROM ")]
    actual_storage_matches = bool(model_files) and all(
        p.is_relative_to(paths.directory("models_ollama")) for p in model_files)
    project = "host-check-" + uid()[:8]
    workspace = paths.project_workspace(project)
    workspace.mkdir()
    (workspace / "note.txt").write_text("Synthetic acceptance fixture. Reference code: LOCAL-42.", encoding="utf-8")
    with Store(paths) as store, store.execution_lock():
        Identity(paths).initialize()
        persona = Identity(paths).current()
        memory = Memory(store)
        old = memory.remember(project, "The project colour is blue", "fixture://original",
                              sensitivity="internal", evidence_status="verified")
        latest = memory.remember(project, "The project colour is green", "fixture://replacement",
                                 sensitivity="internal", evidence_status="verified", supersedes=[old])
        task_id = Journal(store).create(
            'Execute both read_text for note.txt and search_memory for query "colour". '
            'Then report the reference code and the latest colour decision. Read-only.', project,
            {"files": ["note.txt"], "memory_classes": ["public", "internal"]})
    with Store(paths) as store:
        result = Agent(store, model).run(task_id)
    with Store(paths) as store:
        records = Memory(store).search("colour", project_id=project)
        identity_survived = Identity(paths).current() == persona
        task_survived = Journal(store).get(task_id)["state"] == result["task"]["state"]
    actions = result["actions"]
    operations = {a["request"]["operation"] for a in actions if a["status"] == "verified"}
    answer = (result["result"] or {}).get("answer", "")
    checks = {"local_task_completed": result["task"]["state"] == "completed",
              "both_read_tools_verified": operations == {"read_text", "search_memory"},
              "expected_answer": "LOCAL-42" in answer and "green" in answer.lower(),
              "memory_restart_and_history": {r["id"] for r in records} == {old, latest},
              "persona_restart": identity_survived, "journal_restart": task_survived,
              "windows_user_model_path": model_storage_status(paths)["windows_user_value_matches"],
              "actual_model_files_on_root": actual_storage_matches}
    return {"timestamp": now(), "synthetic_only": True, "selected_model": smoke,
            "checks": checks, "passed": all(checks.values()), "task_id": task_id,
            "task_state": result["task"]["state"], "block_reason": result["task"]["block_reason"],
            "verified_operations": sorted(operations), "model_comparisons": 0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, help="Explicit test target; creates a synthetic project")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = verify(args.root)
    text = json.dumps(report, indent=2)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    raise SystemExit(0 if report["passed"] else 2)
