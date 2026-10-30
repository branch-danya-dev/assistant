# Incremental releases and exit gates

The canonical status is in `spec/milestones.json`; this document is explanatory.

**M0 — foundation:** requirements-to-task coverage, accepted architecture baseline, JSON Schema examples, Windows/Linux CI, documented threat fixtures and test rubric. No claims about functional agent behavior.

**M1 — local core:** G-drive root resolver, selected local Qwen3.5 model adapter, versioned persona, scoped private SQLite memory, bounded tool calls, trusted risk classification, approvals, audit, crash journal and reconciliation. Demonstrate safe read-only end-to-end execution plus simulated interrupted mutations (SCN-004/005/007/009/010/011).

**M2 — work tools:** file/document/spreadsheet/calculator/browser research tools; five gold-standard acceptance scenarios passing with evidence. Goal: business tasks, not demo chat.

**M3 — persistence and integrations:** durable scheduler, connector-specific reconciliation, bounded concurrency, Telegram bot, email, browser mutations, approved project workflows and notification drafts. Basic crash safety belongs to M1, not this milestone.

**M4 — advanced agent:** Windows desktop adapter, vision, expanded project integrations, voice, remote access, reviewed skill lifecycle and optional cloud model routing. Later additions require functional acceptance and safety evidence, not comparative LLM benchmarks (ADR-015).

### Release policy
A release requires scenario pass rates, safety regression results, user-visible evidence and machine-readable completion records. No claim of completeness from a single happy-path demonstration. The owner decides whether to promote a milestone.
