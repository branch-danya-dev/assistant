# Personal AI Assistant

**M0 complete; M1 partial, working local vertical slice.** Python 3.12+ modular monolith,
SQLite/FTS5, Windows first. Based on Architecture Baseline v1.0 (`c1a0079`).

Первая реализация уже работает: Qwen строит план, агент читает разрешённые текстовые файлы
и проектную память, проверяет результаты и сохраняет журнал. Полнота M1 пока не заявляется.
[Результаты и ограничения](docs/engineering/m1-evidence.md).

## Implemented

- Ollama **qwen3.5:9b**, separate schema-validated planning and final response, numeric loopback
  only, no proxies/redirects/cloud fallback or model comparisons.
- Trusted `read_text` and `search_memory`: exact file scope, project/sensitivity filters,
  traversal/junction/opened-handle checks and independent tool-result verification.
- SQLite migrations and task journal, stable action IDs, exact one-use approvals, pre-dispatch
  commits, persistent stop, explicit resume and `needs_reconciliation` for uncertain effects.
- Sourced versioned memory, preserved supersession, FTS5, retention filtering/index rebuild,
  explicit owner remembering/removal from retrieval and persona independent of model weights.
- CLI for tasks, evidence, approvals, recovery, memory/persona and consistent database backup.

The production registry is read-only. Mutating effects and approval consumption are tested
with synthetic crash fixtures; no real send/purchase/install/delete adapter is active.
LLM summaries are labelled separately from verified tool results. Office/browser integrations,
semantic embeddings, automatic plan revision and safe workspace writes remain open/deferred.

## Windows quick start

```powershell
cd G:\Assistant\repo
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m personal_agent init
.\.venv\Scripts\python.exe -m personal_agent doctor
.\.venv\Scripts\python.exe -m personal_agent demo
```

`demo` uses synthetic data and a deterministic provider, explicitly no LLM inference.
For real tasks, configure Windows User `OLLAMA_MODELS=G:\Assistant\models\ollama`, restart
Ollama Desktop and ensure the selected tag exists. `.env` is not automatically loaded and cannot
configure the separate Desktop process. See the [runbook](docs/engineering/runbook.md).

Place an approved UTF-8 file at `G:\Assistant\workspace\example\note.txt`, then:

```powershell
.\.venv\Scripts\python.exe -m personal_agent run --project example --allow-file note.txt "Read note.txt and summarize it with evidence."
.\.venv\Scripts\python.exe -m personal_agent tasks
.\.venv\Scripts\python.exe -m personal_agent show TASK_ID
```

Only `ASSISTANT_ROOT` (or explicit absolute `--root`) controls application directories.
No fallback to C:. State is outside `repo/`. Model/provider configuration comes from
[spec/model-config.json](spec/model-config.json), not model output or speculative env flags.

## Validation and navigation

```powershell
.\.venv\Scripts\python.exe tools\validate_specs.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m ruff check src tests setup.py
# Explicit synthetic live check; no model pull or comparison:
.\.venv\Scripts\python.exe tools\verify_host.py --root G:\Assistant
```

[AGENTS.md](AGENTS.md) · [Manifest](spec/manifest.json) · [Tasks](spec/tasks.json) ·
[Requirements](spec/requirements.json) · [Scenarios](spec/scenarios.json) ·
[Baseline](docs/engineering/architecture-baseline.md) · [Decisions](spec/decisions.json) ·
[M0 evidence](docs/engineering/m0-evidence.md) · [M1 evidence](docs/engineering/m1-evidence.md) ·
[Documentation index](docs/INDEX.md).

Only synthetic fixtures/evidence belong in Git; private conversations, memory, credentials
and model files do not.
