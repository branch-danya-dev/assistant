"""Explicit owner JSON ingress through the normal plan/worker/verifier/journal path."""
import json

from .calculator_contract import MAX_INPUT, check_input
from .config import AgentError, reject_links
from .journal import Journal
from .orchestrator import Agent


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise AgentError("calculator_invalid_input")
        value[key] = item
    return value


def run(store, args):
    if not args.experimental_calculator:
        raise AgentError("calculator_not_enabled")
    reject_links(args.input)
    with args.input.open("rb") as source:
        raw = source.read(MAX_INPUT + 1)
    if len(raw) > MAX_INPUT:
        raise AgentError("calculator_budget_exhausted")
    try:
        arguments = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object)
    except (ValueError, UnicodeError, RecursionError):
        raise AgentError("calculator_invalid_input") from None
    operation = args.command.replace("-", "_")
    check_input(operation, arguments)

    class OwnerPlan:
        def complete(self, messages, *, task_id):
            context = json.loads(messages[-1]["content"])
            if context["phase"] == "plan":
                return {"steps": [{"task_id": task_id, "capability_id": "CAP-009",
                                   "operation": operation, "arguments": arguments}],
                        "answer": "", "evidence_refs": []}
            return {"steps": [], "answer": "Numerical receipt independently verified; no LLM used.",
                    "evidence_refs": [f"action:{task_id}:0"]}

    journal = Journal(store)
    task = journal.create("Owner-supplied numerical JSON", args.project,
        {"files": [], "memory_classes": [], "experimental_calculator": True,
         "intent_class": "private" if args.private_intent else "internal"})
    outcome = Agent(store, OwnerPlan()).run(task)
    outcome["model_inference_used"] = False
    if not args.private_intent:
        journal.trust.require_task(task, sink="diagnostics")
        actions = journal.db.execute("SELECT result FROM actions WHERE task_id=? AND status='verified'",
                                     (task,)).fetchall()
        outcome["calculations"] = [json.loads(a[0]) for a in actions]
    return outcome
