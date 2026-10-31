"""Optional isolated selected-Qwen smoke and CAP-009 workflow, never a CI live gate."""
import argparse
import json
from pathlib import Path

from personal_agent.calculator_verify import verify
from personal_agent.config import AgentError, Paths, specification
from personal_agent.identity import Identity
from personal_agent.journal import Journal
from personal_agent.models import Ollama
from personal_agent.orchestrator import Agent
from personal_agent.storage import Store, encode


def check(root):
    paths = Paths(root)
    if paths.root.exists():
        raise AgentError("calculator_invalid_input")
    model = Ollama()
    smoke = model.smoke()
    smoke_passed = (smoke.get("text_generation") == "pass"
                    and smoke.get("structured_tool_intent") == "pass"
                    and smoke.get("reachable") is True and smoke.get("installed") is True)
    paths.bootstrap()
    with Store(paths) as store:
        Identity(paths).initialize()
        arguments = specification("examples/calculate-input.json")
        journal = Journal(store)
        task = journal.create("Use CAP-009/calculate with exactly these arguments, then cite its "
            "action evidence and report the value. Do not revise: " + encode(arguments), "numeric-live",
            {"files": [], "memory_classes": [], "experimental_calculator": True},
            budget={"model_limit": 2, "tool_limit": 1, "wall_seconds": 180})
        outcome = Agent(store, model).run(task)
        actions = outcome["actions"]
        exact = False
        if len(actions) == 1 and actions[0]["status"] == "verified":
            action = journal.action(actions[0]["id"])
            request, receipt = json.loads(action["request"]), json.loads(action["result"])
            verify("calculate", arguments, receipt)
            exact = (request["arguments"] == arguments and request["operation"] == "calculate"
                     and receipt["result"]["number"]["value"] == "0.30"
                     and action["effect"] == "read" and action["attempts"] == 1
                     and action["approval_id"] is None)
        checks = {"smoke": smoke_passed, "completed": outcome["task"]["state"] == "completed",
                  "exact_verified_calculation": exact,
                  "no_approval": store.connection.execute("SELECT count(*) FROM approvals").fetchone()[0] == 0}
        passed = all(checks.values())
        return {"passed": passed, "status": "PASSED" if passed else "FAILED", "checks": checks,
                "model": "qwen3.5:9b", "model_calls": 2 + journal.get(task)["budget"]["model_calls"],
                "state": outcome["task"]["state"], "block_reason": outcome["task"]["block_reason"],
                "synthetic_only": True, "hardware_or_model_blobs_certified": False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = check(args.root)
    except Exception as exc:
        report = {"passed": False, "status": "FAILED",
                  "error": str(exc) if isinstance(exc, AgentError) else "live_gate_failed"}
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] is True else 2


if __name__ == "__main__":
    raise SystemExit(main())
