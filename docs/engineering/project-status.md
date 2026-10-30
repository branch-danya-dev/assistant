# Project status (baseline updated 2026-10-30)

- Stage: conceptual architecture and project bootstrap; no working personal assistant yet.
- Real functional adapters: **none**.
- Runtime inference: **not implemented or installed by this repository**.
- Owner-selected default local model: **Ollama `qwen3.5:9b`** (ADR-015, `spec/model-config.json`).
- Comparative model evaluations: **out of scope by owner choice**; functional smoke and safety checks remain required.
- Built today: agent instructions, machine-readable requirements/tasks/capability list, decision register, contracts, initial typed ports, validator, unittest, CI workflow.
- Open architecture choices: vector index, UI framework, production API auth, permissions details, licensing, sandbox implementation and budgets. Local model selection is **not** open.
- Next: TASK-001..003 then M1 in dependency order; TASK-006 implements the chosen Ollama adapter.
- GitHub repository: `branch-danya-dev/assistant`; changes should go through branches and reviewable PRs.
