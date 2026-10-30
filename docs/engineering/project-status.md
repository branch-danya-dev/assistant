# Project status — Architecture Baseline v1.0 (2026-10-30)

- Stage: architecture/specification and project bootstrap; autonomous assistant runtime **not implemented**.
- Selected local LLM: Ollama `qwen3.5:9b` (ADR-015); no comparative model ranking.
- Owner-approved Windows root: `G:\Assistant` (ADR-016) with application-relative directory layout (ADR-019).
- Accepted core baseline: modular monolith + SQLite/FTS + model-independent identity/memory + trust boundaries and M1 crash reconciliation (ADRs 002–007, 012, 014, 017–020).
- Specification inventory: **54** requirements, **28** capabilities, **42** traceable tasks, **11** defined scenarios, **20** architectural decisions, **7** JSON Schema contracts with synthetic examples.
- No real inference, memory store, tool adapters, task runtime, full security harness, or live user data exists in this repository.
- CI checks schemas, spec coverage, references, and contract tests on Windows and Linux. It cannot certify the selected GPU or true task completion yet.
- Next: complete M0 fixture and threat reviews (TASK-001..003, TASK-039/040) before M1 tasks; see `spec/tasks.json`.
- Current repository: `branch-danya-dev/assistant`. Files in `docs/engineering/import-to-github.md` explain how to clone it onto G:.
