# Architecture — modular monolith, local-first

```text
Desktop / API / Telegram (later) / Voice (later)
                       |
              API + Session layer
                       |
            Task Orchestrator <----> Event log / Scheduler
                 |     |                     |
                 |     +----> Policy/Approval Engine
                 |                   |
        Model Router             Tool Dispatcher ----> Adapters (FS, Python, Docs, Excel, Browser...)
                 |                   |
        Local / Cloud LLM       Evidence / Audit Store
                 |
        Context Assembler <----> Memory Manager ----> SQLite/FTS + vector index + source archive
                 |
        Identity / Preferences (versioned, model-independent)
```

## Principles
- One process/codebase **by default** with clear package/module contracts; background workers are logical units, not microservices.
- Stable ports for model runtime, memory, permission, tool registry, orchestration, and interfaces.
- LLMs propose goals and tool intents; deterministic code validates/authorizes/executes.
- Explicit persisted task-state machine and event log; idempotency key on side effects.
- Memory fact + provenance + confidence + time + supersession; not context-window stuffing.
- External results are untrusted; tool outputs cannot amend authorization policy.
- Local first; cloud egress requires per-scope policy and user opt-in.

## Data paths
1. Request enters session; intent/task ID and scopes assigned.
2. Orchestrator reads relevant context/skills under token budget.
3. Model proposes a typed action; policy validates authorization against origin and resource scope.
4. Dispatcher runs bounded adapter; evidence and audit events are persisted.
5. Deterministic verification checks result; memory is updated with references, not unverified claims.
6. Task reaches terminal state, waits for approval, or checkpoints for resume.

## Package boundaries (proposed, NOT present yet)
`core`, `orchestration`, `models`, `memory`, `identity`, `tools`, `security`, `evolution`, `api`, `infrastructure`, `interfaces`. All are future modules; the existing `src/personal_agent/ports.py` is only a starter contract.

## Architectural constraints
Host initially Windows, Python 3.12+, single user, SQLite starting point. Provider names and UI stack are provisional; no assumptions of universal tool support or identical model capabilities.

## Binding implementation baseline (ADR-002/003/004/005/006/007/012/014/017/018/019/020)

- Initial application is a single-user Python modular monolith on Windows; SQLite/FTS5 for canonical records and an optional independently replaceable semantic index.
- Persona stored outside LLM weights; context retrieval is scope-filtered; tool intents never confer privilege.
- Effective tool permissions come from an owner-approved registry and actual arguments, never model text.
- M1 includes durable journal, approval consumption, safe restart and reconciliation; M3 adds scheduling and external connector recovery.
- `ASSISTANT_ROOT` is the only absolute application-root setting; no silent fallback to another drive.
- See `docs/architecture/identity.md`, `orchestration.md`, `tools.md` and `storage.md`.
