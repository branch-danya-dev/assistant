"""Task transitions, effect-bound one-use approval, durable dispatch and recovery."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

from .config import AgentError, validate
from .storage import Store, encode, now, uid

TRANSITIONS = {
    "created": {"planned", "cancelled", "failed"},
    "planned": {"queued", "paused", "cancelled", "failed"},
    "queued": {"running", "paused", "cancelled"},
    "running": {"waiting_approval", "paused", "blocked", "needs_reconciliation",
                "completed", "failed", "cancelled"},
    "waiting_approval": {"queued", "paused", "blocked", "cancelled"},
    "paused": {"queued", "cancelled"},
    "blocked": {"queued", "cancelled", "failed"},
    "needs_reconciliation": {"blocked", "queued", "failed", "cancelled"},
    "completed": set(), "failed": set(), "cancelled": set(),
}


def digest(value: object) -> str:
    return hashlib.sha256(encode(value).encode()).hexdigest()


class Journal:
    def __init__(self, store: Store):
        self.store = store
        self.db = store.connection

    def get(self, task_id: str) -> dict:
        row = self.db.execute("SELECT document FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row is None:
            raise AgentError("task_not_found")
        return json.loads(row[0])

    def scope(self, task_id: str) -> dict:
        self.get(task_id)
        return json.loads(self.db.execute("SELECT scope FROM tasks WHERE id=?", (task_id,))
                          .fetchone()[0])

    def events(self, task_id: str) -> list[dict]:
        return [json.loads(row[0]) for row in self.db.execute(
            "SELECT document FROM events WHERE task_id=? ORDER BY sequence", (task_id,))]

    def _save(self, task: dict):
        validate("task-state", task)
        self.db.execute("UPDATE tasks SET state=?,document=? WHERE id=?",
                        (task["state"], encode(task), task["task_id"]))

    def _event(self, task_id: str, kind: str, payload: dict | None = None,
               refs: tuple[str, ...] = (), actor: str = "system", key: str | None = None):
        task = self.get(task_id)
        seq = task.get("last_event_sequence", 0) + 1
        event = dict(event_id=uid(), task_id=task_id, sequence=seq, kind=kind,
                     timestamp=now(), actor=actor, evidence_refs=list(refs),
                     payload=payload or {}, idempotency_key=key)
        validate("task-event", event)
        self.db.execute("INSERT INTO events VALUES (?,?,?)", (task_id, seq, encode(event)))
        task.update(last_event_sequence=seq, updated_at=now())
        self._save(task)

    def _transition(self, task_id: str, state: str, reason: str | None = None):
        task = self.get(task_id)
        if state not in TRANSITIONS[task["state"]]:
            raise AgentError("invalid_task_transition")
        if task["state"] == "needs_reconciliation" and state in ("queued", "blocked"):
            if self.db.execute("SELECT 1 FROM actions WHERE task_id=? AND status IN"
                               " ('uncertain','dispatched')", (task_id,)).fetchone():
                raise AgentError("unresolved_effects")
        task.update(state=state, updated_at=now(), block_reason=reason)
        self._save(task)
        kind = {"running": "started", "waiting_approval": "approval_requested",
                "needs_reconciliation": "reconciliation_required"}.get(state, state)
        self._event(task_id, kind, {"reason": reason} if reason else {})

    def transition(self, task_id: str, state: str, reason: str | None = None):
        with self.store.transaction():
            self._transition(task_id, state, reason)

    def create(self, intent: str, project_id: str, scope: dict, *, budget: dict | None = None) -> str:
        if not isinstance(intent, str) or not intent.strip() or len(intent) > 8000:
            raise AgentError("invalid_intent")
        self.store.paths.project_workspace(project_id)
        limits = dict(model_limit=20, tool_limit=40, wall_seconds=900,
                      model_calls=0, tool_calls=0, deadline=None, cloud_cost_limit=0)
        if budget:
            for key, maximum in (("model_limit", 20), ("tool_limit", 40), ("wall_seconds", 900)):
                value = budget.get(key, limits[key])
                if type(value) is not int or not 1 <= value <= maximum:
                    raise AgentError("invalid_budget")
                limits[key] = value
        task_id = uid()
        task = dict(task_id=task_id, intent=intent, project_id=project_id, state="created",
                    step_ids=[], budget=limits, created_at=now(), last_event_sequence=0,
                    result_refs=[], block_reason=None)
        validate("task-state", task)
        with self.store.transaction():
            self.db.execute("INSERT INTO tasks(id,state,document,scope) VALUES (?,?,?,?)",
                            (task_id, "created", encode(task), encode(scope)))
            self._event(task_id, "created", actor="owner")
            self._transition(task_id, "planned")
        return task_id

    def set_plan(self, task_id: str, requests: list[dict]):
        if not isinstance(requests, list) or len(requests) > 40:
            raise AgentError("plan_budget_exceeded")
        for request in requests:
            validate("tool-invocation", request)
            if request["task_id"] != task_id:
                raise AgentError("task_scope_mismatch")
        with self.store.transaction():
            task = self.get(task_id)
            if task["step_ids"] or task["state"] != "running":
                raise AgentError("plan_already_set_or_task_not_running")
            task["step_ids"] = [f"{task_id}:{i}" for i in range(len(requests))]
            self._save(task)
            self.db.execute("UPDATE tasks SET plan=? WHERE id=?", (encode(requests), task_id))
            self._event(task_id, "planned", {"steps": len(requests), "plan_digest": digest(requests)})

    def plan(self, task_id: str) -> list[dict]:
        return json.loads(self.db.execute("SELECT plan FROM tasks WHERE id=?", (task_id,))
                          .fetchone()[0])

    def stopped(self) -> bool:
        return self.db.execute("SELECT value FROM controls WHERE name='stopped'").fetchone()[0] == "1"

    def stop(self, stopped: bool = True):
        with self.store.transaction():
            self.db.execute("UPDATE controls SET value=? WHERE name='stopped'", (str(int(stopped)),))

    def start(self, task_id: str, *, resume: bool = False):
        with self.store.transaction():
            task = self.get(task_id)
            if self.stopped():
                raise AgentError("emergency_stop_active")
            if task.get("block_reason") == "reconciled_create_new_task":
                raise AgentError("reconciled_action_requires_new_task")
            if task["state"] == "planned":
                self._transition(task_id, "queued")
            elif task["state"] in ("paused", "blocked") and resume:
                self._transition(task_id, "queued")
                self._event(task_id, "resumed", actor="owner")
            elif task["state"] != "queued":
                raise AgentError("explicit_recovery_or_approval_required")
            task = self.get(task_id)
            if not task["budget"]["deadline"]:
                task["budget"]["deadline"] = (datetime.now(timezone.utc) + timedelta(
                    seconds=task["budget"]["wall_seconds"])).isoformat().replace("+00:00", "Z")
                self._save(task)
            self._transition(task_id, "running")

    def _check_budget(self, task_id: str, kind: str):
        task = self.get(task_id)
        if self.stopped():
            raise AgentError("emergency_stop_active")
        if task["state"] != "running":
            raise AgentError("task_not_running")
        budget = task["budget"]
        if budget["deadline"] and now() >= budget["deadline"]:
            raise AgentError("wall_budget_exhausted")
        if budget[f"{kind}_calls"] >= budget[f"{kind}_limit"]:
            raise AgentError(f"{kind}_budget_exhausted")
        return task

    def model_call(self, task_id: str):
        with self.store.transaction():
            task = self._check_budget(task_id, "model")
            task["budget"]["model_calls"] += 1
            self._save(task)
            self._event(task_id, "checkpointed", {"model_call": task["budget"]["model_calls"]})

    def prepare(self, task_id: str, ordinal: int, request: dict, effect: str, resource: str) -> str:
        action_id = f"{task_id}:{ordinal}"
        fingerprint = digest(dict(request=request, effect=effect, resource=resource,
                                  scope=self.scope(task_id)))
        with self.store.transaction():
            if self.get(task_id)["state"] != "running":
                raise AgentError("task_not_running")
            previous = self.db.execute("SELECT digest FROM actions WHERE id=?", (action_id,)).fetchone()
            if previous:
                if previous[0] != fingerprint:
                    raise AgentError("action_changed_after_prepare")
                return action_id
            self.db.execute("""INSERT INTO actions(id,task_id,ordinal,request,digest,effect,
                            resource,status) VALUES (?,?,?,?,?,?,?,'pending')""",
                            (action_id, task_id, ordinal, encode(request), fingerprint, effect, resource))
            self._event(task_id, "tool_proposed", {"action_id": action_id,
                        "arguments_digest": fingerprint, "effect": effect}, key=action_id)
        return action_id

    def action(self, action_id: str) -> dict:
        row = self.db.execute("SELECT * FROM actions WHERE id=?", (action_id,)).fetchone()
        if row is None:
            raise AgentError("action_not_found")
        return dict(row)

    def request_approval(self, action_id: str) -> str:
        with self.store.transaction():
            action = self.action(action_id)
            if action["status"] != "pending":
                raise AgentError("action_not_pending")
            approval_id = uid()
            request = json.loads(action["request"])
            approval = dict(approval_id=approval_id, task_id=action["task_id"],
                            capability_id=request["capability_id"], arguments_digest=action["digest"],
                            resource=action["resource"], side_effect=action["effect"],
                            expires_at=(datetime.now(timezone.utc) + timedelta(minutes=10))
                            .isoformat().replace("+00:00", "Z"), status="pending", approved_by=None)
            validate("approval-request", approval)
            self.db.execute("INSERT INTO approvals VALUES (?,?,?)",
                            (approval_id, action_id, encode(approval)))
            self.db.execute("UPDATE actions SET approval_id=? WHERE id=?", (approval_id, action_id))
            self._transition(action["task_id"], "waiting_approval")
        return approval_id

    def approval(self, approval_id: str) -> dict:
        row = self.db.execute("SELECT document FROM approvals WHERE id=?", (approval_id,)).fetchone()
        if not row:
            raise AgentError("approval_not_found")
        return json.loads(row[0])

    def approve(self, approval_id: str, expected_digest: str):
        """Owner UI only. Never expose this as an LLM tool."""
        with self.store.transaction():
            approval = self.approval(approval_id)
            if (approval["status"] != "pending" or approval["expires_at"] <= now()
                    or approval["arguments_digest"] != expected_digest
                    or self.get(approval["task_id"])["state"] != "waiting_approval"):
                raise AgentError("approval_invalid_or_expired")
            approval.update(status="approved", approved_by="local_owner")
            self.db.execute("UPDATE approvals SET document=? WHERE id=?", (encode(approval), approval_id))
            self._event(approval["task_id"], "approved", {"approval_id": approval_id}, actor="owner")
            self._transition(approval["task_id"], "queued")

    def dispatch(self, action_id: str, *, approval_required: bool):
        with self.store.transaction():
            action = self.action(action_id)
            if action["status"] != "pending":
                raise AgentError("action_not_replayable")
            task = self._check_budget(action["task_id"], "tool")
            if action["attempts"] >= 3:
                raise AgentError("read_retry_budget_exhausted")
            # Effects always need approval, even if a caller accidentally passes False.
            if approval_required or action["effect"] != "read":
                approval = self.approval(action["approval_id"])
                if (approval["status"] != "approved" or approval["expires_at"] <= now()
                        or approval["arguments_digest"] != action["digest"]):
                    raise AgentError("approval_invalid_or_expired")
                approval["status"] = "consumed"
                self.db.execute("UPDATE approvals SET document=? WHERE id=?",
                                (encode(approval), approval["approval_id"]))
                self._event(action["task_id"], "approval_consumed",
                            {"approval_id": approval["approval_id"]}, key=action_id)
                task = self.get(action["task_id"])
            task["budget"]["tool_calls"] += 1
            self._save(task)
            self.db.execute("UPDATE actions SET status='dispatched', attempts=attempts+1 WHERE id=?",
                            (action_id,))
            self._event(action["task_id"], "checkpointed", {"dispatch": action_id}, key=action_id)

    def finish(self, action_id: str, result: dict):
        with self.store.transaction():
            action = self.action(action_id)
            if action["status"] != "dispatched":
                raise AgentError("action_not_dispatched")
            self.db.execute("UPDATE actions SET status='verified',result=? WHERE id=?",
                            (encode(result), action_id))
            self._event(action["task_id"], "tool_executed", {"action_id": action_id}, key=action_id)
            self._event(action["task_id"], "verified", {"result_digest": digest(result)},
                        refs=(f"action:{action_id}",), key=action_id)

    def recover(self) -> list[str]:
        """Caller MUST hold Store.execution_lock; no automatic execution here."""
        if not self.store.executing:
            raise AgentError("recovery_requires_executor_lock")
        changed = []
        with self.store.transaction():
            tasks = self.db.execute("SELECT id FROM tasks WHERE state='running'").fetchall()
            for row in tasks:
                task_id = row[0]
                uncertain = False
                for action in self.db.execute(
                        "SELECT * FROM actions WHERE task_id=? AND status='dispatched'", (task_id,)):
                    status = "pending" if action["effect"] == "read" else "uncertain"
                    self.db.execute("UPDATE actions SET status=? WHERE id=?", (status, action["id"]))
                    uncertain |= status == "uncertain"
                self._transition(task_id, "needs_reconciliation" if uncertain else "paused",
                                 "interrupted_dispatch" if uncertain else "interrupted_execution")
                changed.append(task_id)
        return changed

    def reconcile(self, action_id: str, outcome: str, evidence_ref: str):
        """Owner asserts observed outcome. Never replays the old operation."""
        if outcome not in ("applied", "not_applied") or not evidence_ref.strip():
            raise AgentError("reconciliation_evidence_required")
        with self.store.transaction():
            action = self.action(action_id)
            if (action["status"] != "uncertain"
                    or self.get(action["task_id"])["state"] != "needs_reconciliation"):
                raise AgentError("action_not_uncertain")
            self.db.execute("UPDATE actions SET status='reconciled',result=? WHERE id=?",
                            (encode({"outcome": outcome, "evidence_ref": evidence_ref}), action_id))
            self._event(action["task_id"], "reconciled", {"outcome": outcome},
                        refs=(evidence_ref,), actor="owner", key=action_id)
            # Fail closed even for 'not applied': a fresh task and approval are required.
            self._transition(action["task_id"], "blocked", "reconciled_create_new_task")

    def complete(self, task_id: str, result: dict):
        with self.store.transaction():
            if self.stopped():
                raise AgentError("emergency_stop_active")
            task = self.get(task_id)
            if task["budget"]["deadline"] and now() >= task["budget"]["deadline"]:
                raise AgentError("wall_budget_exhausted")
            rows = self.db.execute("SELECT id,status FROM actions WHERE task_id=?", (task_id,)).fetchall()
            if (len(rows) != len(task["step_ids"]) or any(r["status"] != "verified" for r in rows)):
                raise AgentError("unverified_steps")
            refs = [f"action:{r['id']}" for r in rows]
            if not set(result.get("evidence_refs", [])) <= set(refs):
                raise AgentError("fabricated_evidence_reference")
            task["result_refs"] = refs
            self._save(task)
            self.db.execute("UPDATE tasks SET result=? WHERE id=?", (encode(result), task_id))
            self._transition(task_id, "completed")

    def inspect(self, task_id: str) -> dict:
        task = self.get(task_id)
        actions = [dict(row) for row in self.db.execute(
            "SELECT id,status,effect,digest,resource,approval_id,attempts,request FROM actions WHERE task_id=?"
            " ORDER BY ordinal", (task_id,))]
        for action in actions:
            action["request"] = json.loads(action["request"])
        row = self.db.execute("SELECT result FROM tasks WHERE id=?", (task_id,)).fetchone()
        return {"task": task, "actions": actions, "events": self.events(task_id),
                "result": json.loads(row[0]) if row[0] else None}
