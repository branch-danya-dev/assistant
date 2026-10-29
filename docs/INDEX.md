# Documentation routing index

**Agent default:** start at `AGENTS.md` and `spec/manifest.json`, then load only relevant sections.

- [`product/vision.md`](product/vision.md): identity of the product; non-goals.
- [`product/use-cases.md`](product/use-cases.md): priority tasks and acceptance cases.
- [`product/roadmap.md`](product/roadmap.md): implementation order, release gates.
- [`architecture/overview.md`](architecture/overview.md): component boundaries and data flow.
- [`architecture/orchestration.md`](architecture/orchestration.md): execution, retries, scheduling and recovery.
- [`architecture/memory.md`](architecture/memory.md): data, retrieval, provenance, retention.
- [`architecture/models.md`](architecture/models.md): inference and routing policy.
- [`architecture/tools.md`](architecture/tools.md): capability registry and adapters.
- [`architecture/security.md`](architecture/security.md): threat model, authority, approvals.
- [`architecture/evolution.md`](architecture/evolution.md): skill growth and review gates.
- [`architecture/interfaces.md`](architecture/interfaces.md): API surfaces and applications.
- [`engineering/quality.md`](engineering/quality.md): acceptance, test pyramid, evaluation.
- [`engineering/implementation.md`](engineering/implementation.md): development process and local setup.

Canonical datasets: `spec/{manifest,requirements,capabilities,scenarios,decisions,milestones,tasks,components}.json`.
Event/data contracts: `spec/schemas/*.schema.json`.
