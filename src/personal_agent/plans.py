"""Immutable action identities with bounded, compare-and-swap plan revisions."""
from __future__ import annotations

import json

from .config import AgentError, validate
from .storage import encode, now

MAX_REVISIONS = 3
MAX_ACTIONS = 40


class Plans:
    def __init__(self, journal):
        self.journal, self.db = journal, journal.db

    def history(self, task_id):
        return [json.loads(r[0]) for r in self.db.execute(
            "SELECT document FROM plan_revisions WHERE task_id=? ORDER BY revision", (task_id,))]

    def current(self, task_id):
        history = self.history(task_id)
        if history:
            return history[-1]
        # v1 database plans are preserved and gain explicit sequential dependencies on read.
        from .journal import digest
        steps = [{"ordinal": i, "action_id": f"{task_id}:{i}", "request": request,
                  "depends_on": [f"{task_id}:{i-1}"] if i else []}
                 for i, request in enumerate(self.journal.plan(task_id))]
        return {"revision": 0, "steps": steps, "digest": digest(steps), "legacy": True}

    def initial(self, task_id):
        plan = self.current(task_id)
        plan.pop("legacy", None)
        plan.update(timestamp=now(), actor="agent", reason="initial_plan")
        self.db.execute("INSERT INTO plan_revisions VALUES (?,?,?)", (task_id, 0, encode(plan)))

    def revise(self, task_id, proposal, registry, *, actor="owner"):
        from .journal import digest
        if (not isinstance(proposal, dict) or set(proposal) != {"base_digest", "reason", "steps"}
                or not isinstance(proposal["reason"], str) or not 1 <= len(proposal["reason"]) <= 500
                or not isinstance(proposal["steps"], list) or not 1 <= len(proposal["steps"]) <= MAX_ACTIONS):
            raise AgentError("invalid_plan_revision")
        with self.journal.store.transaction():
            task = self.journal.get(task_id)
            if task["state"] not in ("running", "paused", "blocked", "queued", "waiting_approval"):
                raise AgentError("task_not_revisable")
            if task.get("block_reason") == "reconciled_create_new_task":
                raise AgentError("reconciled_action_requires_new_task")
            current = self.current(task_id)
            if proposal["base_digest"] != current["digest"]:
                raise AgentError("stale_plan_revision")
            if current["revision"] >= MAX_REVISIONS:
                raise AgentError("plan_revision_budget_exhausted")
            history = self.history(task_id) or [current]
            known = {s["action_id"]: s for revision in history for s in revision["steps"]}
            active = {s["action_id"] for s in current["steps"]}
            maximum = max((s["ordinal"] for s in known.values()), default=-1)
            steps, seen = proposal["steps"], set()
            new_targets = set()
            scope = self.journal.scope(task_id)
            old_effects = {r[0] for r in self.db.execute(
                "SELECT resource FROM actions WHERE task_id=? AND effect!='read'", (task_id,))}
            for step in steps:
                if (not isinstance(step, dict)
                        or set(step) != {"ordinal", "action_id", "request", "depends_on"}
                        or type(step["ordinal"]) is not int or step["ordinal"] < 0
                        or step["action_id"] != f"{task_id}:{step['ordinal']}"
                        or not isinstance(step["depends_on"], list)
                        or any(not isinstance(d, str) for d in step["depends_on"])
                        or len(set(step["depends_on"])) != len(step["depends_on"])):
                    raise AgentError("invalid_plan_step")
                action_id = step["action_id"]
                if action_id in seen or not set(step["depends_on"]) <= seen:
                    raise AgentError("unresolved_plan_dependencies")
                validate("tool-invocation", step["request"])
                resolved = registry.resolve(step["request"], task, scope)
                if resolved.request != step["request"]:
                    raise AgentError("noncanonical_plan_request")
                if action_id in known:
                    if step != known[action_id] or action_id not in active:
                        raise AgentError("immutable_action_changed")
                else:
                    if step["ordinal"] != maximum + 1:
                        raise AgentError("action_ordinal_reuse_or_gap")
                    maximum += 1
                    if resolved.descriptor["side_effect"] != "read":
                        if resolved.resource in old_effects | new_targets:
                            raise AgentError("non_idempotent_plan_replay_denied")
                        new_targets.add(resolved.resource)
                seen.add(action_id)
            if maximum >= MAX_ACTIONS:
                raise AgentError("plan_action_budget_exhausted")
            for action in self.db.execute("SELECT * FROM actions WHERE task_id=?", (task_id,)):
                if action["status"] in ("dispatched", "uncertain", "reconciled"):
                    raise AgentError("unresolved_effects")
                if (action["id"] not in seen and
                        (action["status"] != "pending" or action["approval_id"] or action["attempts"])):
                    raise AgentError("protected_action_removed")
            if steps == current["steps"]:
                raise AgentError("empty_plan_revision")
            if not self.history(task_id):
                self.initial(task_id)
            revision = {"revision": current["revision"] + 1, "steps": steps,
                        "digest": digest(steps), "previous_digest": current["digest"],
                        "reason": proposal["reason"], "actor": actor, "timestamp": now()}
            self.db.execute("INSERT INTO plan_revisions VALUES (?,?,?)",
                            (task_id, revision["revision"], encode(revision)))
            task["step_ids"] = [s["action_id"] for s in steps]
            self.journal._save(task)
            self.journal._event(task_id, "plan_revised", {
                "revision": revision["revision"], "previous_digest": current["digest"],
                "plan_digest": revision["digest"], "action_ids": task["step_ids"]}, actor=actor)
        return revision
