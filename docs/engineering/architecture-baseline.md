# Architecture Baseline v1.0 — implementation contract

**Date:** 2026-10-30. **Status:** approved design baseline, **not implemented software**. This document reconciles the final pre-development audit and governs the first milestones. Machine-readable sources remain `spec/*.json` and accepted ADRs.

Implementation status is now tracked in `m1-evidence.md` and `spec/`; this document preserves
the approved design and its acceptance gates, rather than claiming the repository is still empty.

## Accepted for M1

| Decision | Contract |
|---|---|
| ADR-001 | Autonomous option C, useful work tools and long-lived project continuity |
| ADR-002 | Single-user Windows Python modular monolith, with explicit module ports |
| ADR-003 | SQLite+FTS5 canonical durable store, optional replaceable semantic index |
| ADR-004/007 | Versioned persona and scoped sourced memory, independent of any LLM |
| ADR-005/015 | Local-first inference, Ollama `qwen3.5:9b`, no comparative LLM tests, consent-gated cloud |
| ADR-006/014/017 | Trusted registry derives actual risk by operation+target; external mutations require exact approval |
| ADR-012/020 | Machine-readable IDs, full requirement-to-task coverage and schema/CI verification |
| ADR-016/019 | `G:\Assistant` default root, only `ASSISTANT_ROOT` is the app-root variable; no fallback |
| ADR-018 | M1 journal, approval consumption, crash-safe needs_reconciliation state |

Changes to accepted decisions require a superseding ADR and migration/compatibility plan. ADR-008's proposed skill-evolution governance remains provisional, although the independently accepted security invariant forbids silent self-modifying core and unapproved tool activation. Other provisional ADRs remain implementation proposals, not automatic mandates.

## M0 exit criteria before M1 work

1. All non-deprecated requirements linked to a planned implementation/deferred task and acceptance evidence; P0 tasks due no later than their requirement milestone.
2. Cross-reference and JSON Schema example validation pass on Ubuntu **and** Windows.
3. Synthetic threat fixtures cover prompt injection, cross-project leakage, forged permissions, unsafe filesystem paths, cloud egress and uncertain external side effects.
4. Current setup instructions reference the existing `branch-danya-dev/assistant` repository, not legacy import archives.
5. Documented design distinguishes `specified` features from real `implemented` work.

## M1 safety-critical paths

A tool invocation from Qwen is untrusted `{task_id,capability_id,operation,arguments}`. Trusted policy registry computes effect, scope and approval. Pre-dispatch journal is committed before side effects, and unknown outcomes after restart become `needs_reconciliation`. No blind retry, duplicate message, unauthorized external mutation or model-provided permission flag.

Persona lives in `data/identity`; private memory in `data/memory`; history in `data/history`; SQL in `data/db`. All derive from configured root, not absolute paths inside code or persisted records.

M1 passes only after actual local-model smoke tests on target host, SCN-004/005/007/009/010/011, persistent state, and proof of denied unauthorized operations. Current CI merely verifies specifications.

## Deferred without blocking M1

M2: office, spreadsheets, browser research and supplier workflows. M3: scheduler, external connectors, cloud escalation, resource telemetry, persona editor, skill candidate capture. M4: advanced desktop, voice, personal Telegram, reviewed tool activation and optional training *feasibility*. No automatic LLM fine-tuning or unauthorized skill activation.

## Quality gate

Before merging any implementation PR: update related REQ/TASK/CAP/SCN IDs and acceptance evidence, tests on Windows/Linux as relevant, redacted logs, reversible data migration when schema changes, and no unapproved external side effects. `AGENTS.md` is the agent entry point.
