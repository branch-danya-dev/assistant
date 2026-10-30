# Owner runbook — first local slice

## Environment and model

Windows, Python 3.12+, SQLite/FTS5, Ollama `qwen3.5:9b`. Code: `G:\Assistant\repo`.
Use `.venv\Scripts\python.exe -m personal_agent` (or the installed `personal-agent` command).
No server/startup daemon is installed. `.env` is a reference template, not automatically loaded.
Export `$env:ASSISTANT_ROOT='G:\Assistant'`, set Windows User environment, or pass an explicit
absolute `--root` before the subcommand. Relative roots fail; there is no C: fallback.

`init` creates the layout, transactional database version 1 and baseline persona, preserving
existing versions. `doctor` reports runtime availability and the separately configured Ollama
User environment. A matching variable does not prove a running process inherited it:
`tools/verify_host.py` also checks actual model blob paths.

Existing model cache migration is explicit. Preview and, only after owner consent, apply:

```powershell
.\tools\configure-ollama-storage.ps1
.\tools\configure-ollama-storage.ps1 -Apply
.\.venv\Scripts\python.exe -m personal_agent doctor
.\.venv\Scripts\python.exe -m personal_agent smoke
.\.venv\Scripts\python.exe tools\verify_host.py --root G:\Assistant
```

The script copies and SHA-256-verifies the existing cache, retains originals, sets User
`ASSISTANT_ROOT`/`OLLAMA_MODELS`, and briefly restarts the already installed Desktop app.
It never downloads weights or removes old files. Differing target files cause an error rather
than overwrite. On verification failure settings stay unchanged; restart the original Ollama
manually before retrying. Source/app/root paths can be passed explicitly.

On a machine with no existing model, follow `docs/architecture/storage.md`, quit/relaunch Ollama,
then explicitly authorize and run `ollama pull qwen3.5:9b`. The application never does this itself.
API references: [chat](https://docs.ollama.com/api/chat),
[structured outputs](https://docs.ollama.com/capabilities/structured-outputs),
[Windows environment](https://docs.ollama.com/faq).

## Tasks, scope and stop

Place UTF-8 files in `G:\Assistant\workspace\PROJECT`. Only exact relative file names explicitly
passed with `--allow-file` can be read. Maximum 32 KiB per regular file; no symlinks, junctions,
hard links, traversal or alternate data streams. Model input has a conservative 6,000-byte
ceiling, context is 8,192 tokens and output is capped at 1,024 tokens. Oversized context pauses
visibly rather than silently truncating evidence. This is an application boundary, not isolation
against another process with the same Windows account modifying the whole app/database.

```powershell
# In these examples, python means the project virtualenv Python.
python -m personal_agent run --project example --allow-file note.txt "Read note.txt and report facts with evidence."
python -m personal_agent tasks
python -m personal_agent show TASK_ID
python -m personal_agent stop
python -m personal_agent clear-stop
python -m personal_agent recover
python -m personal_agent resume TASK_ID
python -m personal_agent cancel TASK_ID
```

Stop persists and blocks new dispatch. It cannot undo in-flight operations; active local
inference can take its remaining timeout to return. Ctrl+C requests stop and recovery.
One OS lock serializes execution/recovery; inspection and stop use separate SQLite connections.
Recovery never starts work automatically. Verified actions are skipped on explicit resume;
interrupted reads have at most three total attempts. Budgets survive restart: 20 model calls,
40 tool dispatches, eight steps per initial linear plan, 15 minutes per task, zero cloud spend.
Create a new task when a budget is exhausted. Live plan revision remains TASK-009 work.

## Approval and reconciliation

`show` includes the exact request, operation, target, digest, status and event sequence.
`approve APPROVAL_ID --digest EXACT_REVIEWED_DIGEST` is an owner CLI action, never an LLM tool.
Approvals expire after ten minutes and are consumed in the same transaction as dispatch.
The production registry currently has only reads: approval cannot activate unsupported writes,
sends, purchases, installs or deletions. Synthetic tests exercise mutating-effect recovery.

An unknown mutating outcome becomes `needs_reconciliation`. Inspect the external state before
`reconcile ACTION_ID --outcome applied|not_applied --evidence SOURCE_REFERENCE`.
For either outcome, the original action remains non-replayable; retry needs a new task/approval.
Connector-specific reconciliation and real external senders remain deferred.

## Memory and identity

```powershell
python -m personal_agent memory add "Use green" --project example --source "owner:decision-1" --sensitivity internal
python -m personal_agent memory search "green" --project example
python -m personal_agent memory add "Use blue" --project example --source "owner:decision-2" --sensitivity internal --supersedes PREVIOUS_ID
python -m personal_agent memory remove RECORD_ID --project example
python -m personal_agent memory reindex
python -m personal_agent persona
```

Remembering is explicit; generated answers are never promoted automatically. New records default
to private. `--include-private` grants local access to that project's private records. Restricted
records are excluded from M1 model context. Project/sensitivity filters precede candidate ranking.
Search is lexical FTS5 with chronological ordering, not semantic embeddings. Supersession retains
old decisions and sources; unverified claims cannot replace verified ones. Temporary expiry hides
records without deleting evidence. Removal excludes a record from retrieval and rebuilt indexes;
it is **not physical erasure from database pages or backups**. Full export/erasure remains M3.

Persona versions are immutable files in `data/identity`, independent of the provider. Defaults
come from the baseline, not inferred personal data. The owner Python API supports new versions;
an interactive persona editor remains M3. Tool execution evidence and LLM summaries are labelled
separately: a model's narrative is not independently fact-checked merely because its reads passed.

## Backup, restore and migration

`backup` uses SQLite online backup and integrity checking; it backs up the database only.
For a full backup, stop execution/close the app and copy `data/identity`, source archives and
approved workspace alongside the DB backup. Canonical task/history/memory rows currently live
in `data/db/agent.sqlite3`; other layout partitions are reserved for later archives and exports.
Do not naively copy an active SQLite file without its WAL/online backup. Never put state in Git.

Restore into a new empty root: run `init`, close the app, place the verified DB backup at the
configured `data/db/agent.sqlite3`, and restore persona files without replacing differing versions.
Run `recover`, `tasks`, `persona`, memory search, `doctor`, then the synthetic host check. Keep the
old root until verification passes. Changing only `ASSISTANT_ROOT` relocates application paths;
separately update Ollama User `OLLAMA_MODELS` and restart Desktop.

Make and verify a backup before future schema upgrades. Version 1 migration is transactional;
newer unknown schema versions are rejected. Rollback restores a backup with matching code,
not a destructive down migration. A G: backup is not disaster recovery; retain an encrypted
off-disk copy separately.
