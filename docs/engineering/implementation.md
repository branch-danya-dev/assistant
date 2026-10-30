# Implementation guide

## Repo state
**First M1 slice implemented; M1 remains partial.** Runtime modules implement storage, journal,
memory, identity, trusted reads, Ollama and a CLI. CI covers security, crash and local HTTP
integration tests. See `m1-evidence.md` for actual checks and `runbook.md` for operation.

## Owner Windows location

Clone to `G:\Assistant\repo`, not the system disk. Before running code or downloading the model, provision `G:\Assistant` using the procedure in `docs/architecture/storage.md`. The root is configurable through `ASSISTANT_ROOT`, while Ollama Desktop requires a user-level `OLLAMA_MODELS=G:\Assistant\models\ollama` and a restart. CI and isolated tests may explicitly set temporary roots. Do not hardcode G: in modules or silently fall back to C:.

## Local development (Windows PowerShell)

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python tools/validate_specs.py
python -m unittest discover -s tests -v
```

## Contract and CI discipline

The canonical M1 baseline is `docs/engineering/architecture-baseline.md`, with threat cases in `docs/engineering/threat-fixtures.md`. Every non-deprecated REQ must link to a TASK; every TASK has verifiable acceptance. JSON Schema examples under `spec/examples/` are checked with `jsonschema` on both Ubuntu and Windows runners. Model comparison is out of scope (ADR-015), but Qwen3.5 adapter smoke tests and security/functional acceptance are mandatory when the runtime exists. GitHub Actions cannot validate the owner's physical GPU/G: without an explicitly configured self-hosted runner.

## Delivery order
1. M0: validate docs, contracts and decisions.
2. M1: root path bootstrap / typed task journal and safe crash reconciliation / authorization / source-provenance memory, private scopes and stable persona / selected Ollama Qwen3.5 adapter / read-only tool.
3. M2: file/document/spreadsheet/calculator/browser; prove scenarios.
4. M3+: scheduler, remote integrations and self-improvement experiments.

## How an agent picks work
Load manifest -> choose lowest unblocked `TASK-###` in current milestone -> read related REQ/CAP/SCN/ADR entries -> implement one task -> tests and traceability -> submit PR with evidence. Do not start future milestones prematurely.

## Dependencies
Runtime reuses the approved `jsonschema` validator pinned to tested version `4.26.0`.
HTTP, SQLite and filesystem boundaries use the standard library. No additional provider SDK,
daemon, cloud service or plugin is required. Package builds include canonical spec resources.

## Changes in this repo
Specification changes must update the machine-readable records first and then explanatory Markdown. Changed decisions should be added as new ADR entries or explicitly marked superseded. The owner makes the final decision on unresolved architecture trade-offs.
