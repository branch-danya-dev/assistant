# Personal AI Assistant — agent-first repository

**Status:** `PLANNING` · **Implementation:** not started · **Target host:** Windows desktop · **Primary language:** Python.

A local-first, hybrid-model, long-lived personal AI agent with a stable identity, persistent project memory, controlled autonomy and extensible tools. It is a proposed engineering system, **not** a claim of a sentient AI or a working product.

> Russian summary: персональный ИИ-агент для Windows с независимой от LLM личностью, долговременной памятью, локальными/облачными моделями, инструментами и автономными задачами. Сейчас репозиторий содержит архитектуру, контракты и план реализации; работающее приложение ещё не создано.

## Start here

- **Agents:** [`AGENTS.md`](AGENTS.md) is the mandatory orientation and safety file.
- **Canonical machine-readable index:** [`spec/manifest.json`](spec/manifest.json).
- **Product intent:** [`docs/product/vision.md`](docs/product/vision.md).
- **Requirements:** [`spec/requirements.json`](spec/requirements.json).
- **Architecture:** [`docs/architecture/overview.md`](docs/architecture/overview.md).
- **Decision register:** [`spec/decisions.json`](spec/decisions.json).
- **Implementation queue:** [`spec/tasks.json`](spec/tasks.json).
- **Milestones and gates:** [`spec/milestones.json`](spec/milestones.json).
- **Validation:** `python tools/validate_specs.py` and `python -m unittest discover -s tests -v`.

## Technical baseline (provisional)

Windows desktop (OS version to verify); Ryzen 5 7600X; RTX 5070 Ti 16 GB VRAM; 32 GB RAM; SSD. Local inference via replaceable provider adapters (Ollama is a proposed first adapter), optional explicit cloud API. Python 3.12+; modular monolith; SQLite + FTS5 first; semantic retrieval via replaceable index; Tauri/React UI later. **Benchmarks and final model choice are pending.**

## Conventions

The JSON specifications in `spec/` are canonical for structured status and traceability. Markdown in `docs/` supplies rationale and execution guidance. If they disagree, **do not silently choose**: log a documentation defect and reconcile them. Every feature has a stable requirement ID and verifiable acceptance tests. Proposed capabilities must never be presented as implemented.

No credentials, private conversations, uploaded project files, local memory stores, model weights or personal information should be committed. See `.gitignore` and the security policy.

## Current scope

This is a **planning and project-bootstrap baseline**. Source packages, runtime infrastructure and production integrations are future work. Do not assume any feature is already implemented because it is described in a requirement.
