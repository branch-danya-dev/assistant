# Incremental releases and exit gates

The canonical status is in `spec/milestones.json`; this document is explanatory.

**M0 — foundation:** project/contract schemas, validation, tests, traceability, baseline security invariants. No claims about functional agent behavior.

**M1 — local core:** local model adapter, conversation session, task state, bounded tool invocation, scoped SQLite-backed memory, authorization and auditing. Demonstrate real end-to-end safe read-only execution.

**M2 — work tools:** file/document/spreadsheet/calculator/browser research tools; five gold-standard acceptance scenarios passing with evidence. Goal: business tasks, not demo chat.

**M3 — persistence and integrations:** scheduler, retry/recovery, Telegram bot, approved project workflows and notification drafts; test safe restart and external-action approval.

**M4 — advanced agent:** Windows desktop adapter, vision, expanded project integrations, voice, remote access, reviewed skill lifecycle and optional cloud model routing. Later additions require functional acceptance and safety evidence, not comparative LLM benchmarks (ADR-015).

### Release policy
A release requires scenario pass rates, safety regression results, user-visible evidence and machine-readable completion records. No claim of completeness from a single happy-path demonstration. The owner decides whether to promote a milestone.
