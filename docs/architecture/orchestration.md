# Task orchestration, safety and crash recovery (ADR-018)

## State machine

Task states: `created`, `planned`, `queued`, `running`, `waiting_approval`, `paused`, `blocked`, `needs_reconciliation`, `completed`, `partial`, `failed`, `cancelled`. Canonical JSON contract: `spec/schemas/task-state.schema.json`.

| From | Allowed next states |
|---|---|
| created | planned, cancelled, failed |
| planned | queued, paused, cancelled, failed |
| queued | running, paused, cancelled |
| running | waiting_approval, paused, blocked, needs_reconciliation, completed, partial, failed, cancelled |
| waiting_approval | queued, paused, blocked, cancelled |
| paused | queued, cancelled |
| blocked | queued only after resolving blocker, cancelled, failed |
| needs_reconciliation | blocked, queued only after verified outcome and explicit transition, failed, cancelled |
| completed, partial, failed, cancelled | terminal; create a new task to retry |

A new retry is a new action ID; a previous uncertain side effect **must not** be replayed. No unconditional transition from `needs_reconciliation` to `running`.

## Execution sequence

1. Create task and durable plan with deterministic IDs, scoped permissions and explicit budgets.
2. Model proposes a typed tool **intent**, validated against `tool-invocation.schema.json`. The model does not choose authoritative side effect, scope, or permission.
3. Registry/policy derives effective risk from operation and actual resource arguments; evaluate approval and data sensitivity.
4. **Before execution**, atomically persist action intent, idempotency key, effective target, granted approval and attempt state. Approval is bound to exact action/arguments and consumed only once.
5. Execute through bounded trusted adapter. Record tool outcome, evidence, and verification in an event journal. Checkpoint task state in transactions.
6. On timeout/crash after dispatch with unknown outcome: mark `needs_reconciliation`, suspend further mutating steps, inspect external state before deciding whether already committed.
7. Update sourced project memory only for verified outcomes; publish final result with evidence or a visible blocked status.

Never infer success from an LLM response. Retain evidence references, input digests and failure states without leaking credentials. Use monotonic event sequence within a task.

## M1 minimum versus M3 extensions

**M1 (TASK-004 / TASK-005 / TASK-029 / TASK-009):** durable task/step journal, policy checks, approval consumption, minimal restart recovery, no duplicate side effects, timeouts and emergency stop, clear `needs_reconciliation` state. SCN-005 and SCN-010 must pass on fixture/simulated interruptions.

**M3 (TASK-016):** durable scheduler, trigger subscriptions, connector-specific reconciliation adapters, background task priorities and external event watches. M3 is not required for baseline correctness after crash.

## Initial default safety budgets (configurable under user control)

- Maximum 20 model calls per task and 40 tool calls per task.
- Maximum 2 automatic retries per individual idempotent read-only step.
- Maximum 15 minutes wall-clock per execution segment; pause and request owner extension rather than silently continuing.
- Cloud API spending limit = 0 unless the owner enables cloud and explicitly sets a cost cap.
- Independently cap context length, memory retrieval, concurrency and GPU residency according to actual host resources.

Budgets are **proposed implementation defaults**, not measured runtime values. Dynamic elevation requires a policy decision and audit; the user can cancel a task at any point. Tools with uncertain side effects are not blindly retried.

## Concurrency

Read-only independent steps may run concurrently under bounded resource budgets. Writes targeting the same resource serialize; approval gates and journal entries must be transactionally consistent. Shared inference uses a bounded request queue.

## Verification

See `spec/scenarios.json`, especially SCN-005 and SCN-010. Test simulated crashes before dispatch, during tool execution, after external confirmation and before journal commit. Neither a network timeout nor process exit proves an action failed.

## Bounded content outcome (ADR-022)

`partial` is terminal and retains verified action evidence while explicitly refusing full semantic
completion when source content cannot fit the model context. It exits CLI with code 2.
See `../engineering/m1-review-fixes.md` for exact projection, append-revision and migration rules.
