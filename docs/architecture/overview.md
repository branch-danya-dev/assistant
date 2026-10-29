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
