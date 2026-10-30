"""Bounded LLM views of durable evidence; never truncate a source or plan in place."""
from __future__ import annotations

import json

from .data_policy import tool_result
from .journal import digest
from .models import MAX_CONTEXT_BYTES
from .storage import encode


def message_bytes(messages):
    # Count the actual nested JSON escaping used by Ollama, not raw source characters.
    return len(encode(messages).encode("utf-8"))


def final_context(journal, task, scope, persona, system):
    """Full results stay in actions.result and create arguments in immutable plan history.

    Include each read result entirely or only its receipt. If even receipts do not fit,
    return no model request: trusted code can report a partial result without an endless
    context-budget pause. Append revisions refer to the saved base, not copied payloads.
    """
    plan = journal.plans.current(task["task_id"])
    history = journal.plans.history(task["task_id"]) or [plan]
    next_ordinal = 1 + max(s["ordinal"] for p in history for s in p["steps"])
    observations, originals, coverage = [], [], []
    for step in plan["steps"]:
        ref = f"action:{step['action_id']}"
        receipt = journal.evidence(task["task_id"], ref, task["project_id"])
        result = json.loads(journal.action(step["action_id"])["result"])
        tool_result(step["request"], result, task, scope)
        operation = step["request"]["operation"]
        observations.append({"evidence_ref": ref, "result_digest": receipt["result_digest"],
                             "operation": operation, "content_visibility": "receipt_only",
                             "output": receipt["output"]})
        originals.append(result)
        coverage.append({"evidence_ref": ref, "result_digest": receipt["result_digest"],
                         "operation": operation, "content_visibility": "receipt_only"})
    context = {"phase": "final", "task_id": task["task_id"], "owner_intent": task["intent"],
               "approved_files": scope["files"], "allowed_create_files": scope.get("create_files", []),
               "persona": persona, "untrusted_observations": observations,
               "current_plan": {"digest": plan["digest"], "revision": plan["revision"],
                                "retained_steps": len(plan["steps"]), "next_ordinal": next_ordinal,
                                "last_action_id": plan["steps"][-1]["action_id"],
                                "requests": "saved_in_journal_not_in_model_context"},
               "content_notice": "receipt_only is NOT source content or a semantic summary. "
                   "Never claim to have analyzed withheld content. Full results remain saved."}

    def messages():
        return [{"role": "system", "content": system}, {"role": "user", "content": encode(context)}]

    if message_bytes(messages()) > MAX_CONTEXT_BYTES:
        return None, {"mode": "receipts_exceed_context_no_final_model_call", "coverage": coverage,
                      "prompt_bytes": 0, "plan_digest": plan["digest"]}
    for index, observation in enumerate(observations):
        if observation["operation"] == "create_text":
            continue  # Exact bytes were verified by the observer, not by the model.
        previous = observation["output"]
        observation.update(output=originals[index], content_visibility="full")
        if message_bytes(messages()) > MAX_CONTEXT_BYTES:
            observation.update(output=previous, content_visibility="receipt_only")
        else:
            coverage[index]["content_visibility"] = "full"
    result = messages()
    return result, {"mode": "bounded_evidence_projection", "coverage": coverage,
                    "prompt_bytes": message_bytes(result), "plan_digest": plan["digest"],
                    "projection_digest": digest(context)}


def limited_result(projection):
    """A model cannot turn withheld source content into a semantic success claim."""
    coverage = projection["coverage"]
    partial = (projection["prompt_bytes"] == 0 or any(
        c["operation"] != "create_text" and c["content_visibility"] != "full" for c in coverage))
    return {"answer": (
        "Tool operations were verified and their complete results retained. "
        "Some source content was not supplied to the model; full semantic analysis is NOT complete. "
        "Review the original sources against the saved bytes/SHA-256 receipts, or start a new task "
        "with smaller owner-prepared sources. Do not repeat completed creates."
        if partial else
        "The exact approved file bytes were created and independently verified. "
        "Use the saved evidence references for bytes and SHA-256. "
        "This confirms file creation only; no semantic validation of its content is claimed."),
        "evidence_refs": [c["evidence_ref"] for c in coverage],
        "verification": "tool_results_verified_semantic_analysis_not_claimed",
        "semantic_analysis": "incomplete" if partial else "not_claimed",
        "verified_steps": len(coverage), "model_context": projection}, partial
