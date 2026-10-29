# Orchestration, scheduling, recovery

## Task states
`created -> planned -> queued -> running -> [waiting_approval | blocked | paused | failed | completed | cancelled]`. Recovery from a non-terminal state must consult the persisted event journal and action idempotency records. Do not replay irreversible operations after a crash without reconciliation.

## Step execution
A task has owner, intent, scope, plan, constraints, budgets, approvals, event history, outputs, evidence, and a deadline/cancellation token. Before executing a tool: validate typed args, effective permission, target scope, budget, timeout and idempotency. After: check outcome independently and record immutable event. Plans are revisable but changes logged.

## Constraints
- Bounded retries with backoff, per-tool allowlists and per-task budgets.
- Pause when authorization is missing, external action cannot be confirmed, or evidence contradicts plan.
- Read-only steps may run concurrently; writes to same resource are serialized.
- LLM calls are shared via a bounded priority queue to manage VRAM and API cost.
- Subtasks may continue while one is awaiting approval; no hidden external side effect.
- Task cancellation must stop new work, cancel safely interruptible steps and report in-flight operations.

## Non-idempotent operations
Outgoing messages, purchases and external mutations require an operation ID and post-operation reconciliation; retries must not result in duplicates. On uncertain outcome, move to `blocked`/`needs_reconciliation`, never pretend an action completed.

## Scheduling
One durable local scheduler is sufficient initially. Trigger types: owner request, explicit schedule, permitted watched events. Unsolicited projects or expensive monitoring must obey owner-approved scope/cadence and quotas.
