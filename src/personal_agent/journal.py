"""Task transitions, effect-bound one-use approval, durable dispatch and recovery."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

from .config import AgentError, safe_relative, validate
from .evidence import project_result, redact, text_receipt
from .plans import Plans
from .storage import Store, encode, now, uid

TRANSITIONS = {
    "created": {"planned", "cancelled", "failed"},
    "planned": {"queued", "paused", "cancelled", "failed"},
    "queued": {"running", "paused", "cancelled"},
    "running": {"waiting_approval", "paused", "blocked", "needs_reconciliation",
                "completed", "partial", "failed", "cancelled"},
    "waiting_approval": {"queued", "paused", "blocked", "cancelled"},
    "paused": {"queued", "cancelled"},
    "blocked": {"queued", "cancelled", "failed"},
    "needs_reconciliation": {"blocked", "queued", "failed", "cancelled"},
    "completed": set(), "partial": set(), "failed": set(), "cancelled": set(),
}


def digest(value: object) -> str:
    return hashlib.sha256(encode(value).encode()).hexdigest()


class Journal:
    def __init__(self, store: Store):
        self.store = store
        self.db = store.connection
        self.plans = Plans(self)

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
        scope = json.loads(encode(scope))
        if scope.get("create_files"):
            from .bounded import run_worker
            scope["create_files"] = [safe_relative(p) for p in scope["create_files"]]
            if len(scope["create_files"]) > 40:
                raise AgentError("scope_budget_exhausted")
            scope["create_bindings"] = run_worker(self.store.paths, {
                "kind": "snapshot", "project": project_id, "files": scope["create_files"]})
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
            self.plans.initial(task_id)
            self._event(task_id, "planned", {"steps": len(requests), "plan_digest": digest(requests)})

    def plan(self, task_id: str) -> list[dict]:
        return json.loads(self.db.execute("SELECT plan FROM tasks WHERE id=?", (task_id,))
                          .fetchone()[0])

    def stopped(self) -> bool:
        return self.db.execute("SELECT value FROM controls WHERE name='stopped'").fetchone()[0] == "1"

    def stop(self, stopped: bool = True):
        with self.store.transaction():
            self.db.execute("UPDATE controls SET value=? WHERE name='stopped'", (str(int(stopped)),))

    def cancel_requested(self, task_id: str) -> bool:
        return self.db.execute("SELECT 1 FROM controls WHERE name=? AND value='1'",
                               (f"cancel:{task_id}",)).fetchone() is not None

    def cancel(self, task_id: str):
        with self.store.transaction():
            task = self.get(task_id)
            if task["state"] == "running":
                self.db.execute("INSERT OR REPLACE INTO controls VALUES (?, '1')", (f"cancel:{task_id}",))
                self._event(task_id, "cancellation_requested", actor="owner")
            elif task["state"] == "needs_reconciliation":
                raise AgentError("unresolved_effects")
            else:
                self._transition(task_id, "cancelled")

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
        if self.cancel_requested(task_id):
            raise AgentError("task_cancel_requested")
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
        planned = next((s for s in self.plans.current(task_id)["steps"]
                        if s["action_id"] == action_id), None)
        if not planned or planned["request"] != request:
            raise AgentError("action_not_in_current_plan")
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
            if effect != "read" and self.db.execute(
                    "SELECT 1 FROM actions WHERE task_id=? AND resource=? AND effect!='read'",
                    (task_id, resource)).fetchone():
                raise AgentError("non_idempotent_plan_replay_denied")
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
            if action["approval_id"]:
                raise AgentError("approval_already_bound")
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
            step = next((s for s in self.plans.current(action["task_id"])["steps"]
                         if s["action_id"] == action_id), None)
            if step is None or any(self.action(d)["status"] != "verified" for d in step["depends_on"]):
                raise AgentError("unresolved_plan_dependencies")
            if action["effect"] != "read" and action["attempts"]:
                raise AgentError("non_idempotent_replay_denied")
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

    def complete(self, task_id: str, result: dict, *, partial: bool = False):
        """Finalize verified actions; partial explicitly does not certify the owner's whole goal."""
        with self.store.transaction():
            if self.stopped():
                raise AgentError("emergency_stop_active")
            if self.cancel_requested(task_id):
                raise AgentError("task_cancel_requested")
            task = self.get(task_id)
            if task["budget"]["deadline"] and now() >= task["budget"]["deadline"]:
                raise AgentError("wall_budget_exhausted")
            rows = self.db.execute("SELECT id,status FROM actions WHERE task_id=?", (task_id,)).fetchall()
            active = [r for r in rows if r["id"] in task["step_ids"]]
            if (len(active) != len(task["step_ids"]) or any(r["status"] != "verified" for r in active)):
                raise AgentError("unverified_steps")
            refs = [f"action:{r['id']}" for r in active]
            provided = result.get("evidence_refs")
            if not isinstance(provided, list) or any(not isinstance(r, str) for r in provided):
                raise AgentError("invalid_evidence_references")
            if not set(provided) <= set(refs):
                raise AgentError("fabricated_evidence_reference")
            if set(provided) != set(refs) or len(provided) != len(refs):
                raise AgentError("missing_or_duplicate_evidence_references")
            task["result_refs"] = refs
            self._save(task)
            self.db.execute("UPDATE tasks SET result=? WHERE id=?", (encode(result), task_id))
            self._transition(task_id, "partial" if partial else "completed",
                             "full_content_analysis_unavailable" if partial else None)

    def inspect(self, task_id: str) -> dict:
        task = self.get(task_id)
        actions = [dict(row) for row in self.db.execute(
            "SELECT id,status,effect,digest,resource,approval_id,attempts,request FROM actions WHERE task_id=?"
            " ORDER BY ordinal", (task_id,))]
        for action in actions:
            action["request"] = json.loads(action["request"])
            args = action["request"]["arguments"]
            if "text" in args:
                args["text"] = text_receipt(args["text"])
            if "query" in args:
                args["query"] = redact(args["query"], 1000)
            if action["status"] == "verified":
                action["evidence_ref"] = f"action:{action['id']}"
                action["evidence"] = self.evidence(task_id, action["evidence_ref"], task["project_id"])
        row = self.db.execute("SELECT result FROM tasks WHERE id=?", (task_id,)).fetchone()
        result = json.loads(row[0]) if row[0] else None
        if result and "answer" in result:
            result["answer"] = redact(result["answer"], 4000)
        task["intent"] = redact(task["intent"])
        plan = self.plans.current(task_id)
        visible_steps = [{k: v for k, v in s.items() if k != "request"} for s in plan["steps"]]
        return {"task": task, "actions": actions, "events": self.events(task_id)[-100:],
                "result": result, "plan": {**plan, "steps": visible_steps},
                "plan_history": [{k: v for k, v in p.items() if k not in ("steps", "reason")}
                                 for p in self.plans.history(task_id)]}

    def evidence(self, task_id: str, ref: str, project: str) -> dict:
        task = self.get(task_id)
        if task["project_id"] != project or not ref.startswith("action:"):
            raise AgentError("evidence_scope_mismatch")
        action = self.action(ref.removeprefix("action:"))
        if action["task_id"] != task_id or action["status"] != "verified" or not action["result"]:
            raise AgentError("evidence_scope_mismatch")
        result = json.loads(action["result"])
        return {"evidence_ref": ref, "result_digest": digest(result), "status": "verified",
                "output": project_result(json.loads(action["request"]), result, project, self.scope(task_id)),
                "view": "bounded_metadata_source_content_withheld"}
