# Owner runbook — M1 local agent

## Environment and model

Windows, Python 3.12+, SQLite/FTS5, Ollama `qwen3.5:9b`. Code: `G:\Assistant\repo`.
Use `.venv\Scripts\python.exe -m personal_agent` (or the installed `personal-agent` command).
No server/startup daemon is installed. `.env` is a reference template, not automatically loaded.
Export `$env:ASSISTANT_ROOT='G:\Assistant'`, set Windows User environment, or pass an explicit
absolute `--root` before the subcommand. Relative roots fail; there is no C: fallback.

`init` creates the layout, transactional database version 3 and baseline persona, preserving
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
ceiling, context is 8,192 tokens and output is capped at 1,024 tokens. Complete results remain
saved; the final prompt includes each source in full or an explicitly marked receipt. Withheld
read content produces terminal `partial` (exit 2), never a full-analysis success claim. Review
original sources against receipts, or prepare smaller sources for a new scoped task; do not
repeat verified creates. Large create completion confirms exact bytes only, not semantic
correctness. Initial oversized intent/persona/scope is still rejected before execution.
See [bounded context and limits](m1-review-fixes.md). This is an application boundary, not isolation
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

Stop persists, blocks new dispatch and terminates the active worker. Cancellation is task-local.
Neither can undo completed effects; unknown creates require reconciliation. Ctrl+C requests stop
and recovery. Tool execution plus verification has a five-second deadline; Ollama a 60-second cap.
One OS lock serializes execution/recovery; inspection and stop use separate SQLite connections.
Recovery never starts work automatically. Verified actions are skipped on explicit resume;
interrupted reads have at most three total attempts. Budgets survive restart: 20 model calls,
40 tool dispatches, eight steps per initial linear plan, 15 minutes per task, zero cloud spend.
Create a new task when a budget is exhausted. Plans allow at most three audited revisions and
40 lifetime action IDs; no ordinal or action ID is recycled.

## Approval and reconciliation

`show` includes operation, target, digest, status, plan revisions and the latest 100 events.
Free-form create text is represented by its byte count and hash. Saved verified result metadata
is available through `show-evidence TASK_ID action:ACTION_ID --project PROJECT --limit 16384`.
Source contents are withheld, including arbitrary secret strings; this view never reads foreign
projects. Use your own local file viewer for content that you are authorized to inspect.
`approve APPROVAL_ID --digest EXACT_REVIEWED_DIGEST` is an owner CLI action, never an LLM tool.
Before approval, `approval-preview APPROVAL_ID --project PROJECT` creates a private JSON file
in the application's cache containing the full exact proposal and scope. Open that file locally
to review the proposed content; the CLI prints only its relative location and approval digest.
It never approves or executes the proposal. Preview files are private state, never Git artifacts.
The cache subdirectory is `approval-previews-v1`: verified user-only Windows DACL, or POSIX
0600 files/0700 directory. TTL is 15 minutes; 256 KiB/file and 64 tracked previews maximum.
Creation cleans expired entries; run `python -m personal_agent cleanup-previews` for repeatable
cleanup after restart. There is no background cleaner: expired files persist until cleanup runs.
Only registered identities are removed; substitutions/unsafe objects are reported as skipped.
Legacy unregistered previews require owner inspection/removal. Deletion is not secure erasure.
Approvals expire after ten minutes and are consumed in the same transaction as dispatch.
The registry permits `create_text` only for exact `--allow-create new.txt` targets in existing
project directories. This allowlist alone does not approve the content: inspect the proposal,
approve its digest, then `resume TASK_ID`. File creation is exclusive; existing targets cause
reconciliation after dispatch and are never overwritten. Approval cannot activate unsupported
sends, purchases, installs, deletion or overwriting.

```powershell
python -m personal_agent run --project example --allow-create result.txt "Create result.txt containing Synthetic result."
python -m personal_agent show TASK_ID
python -m personal_agent approval-preview APPROVAL_ID --project example
python -m personal_agent approve APPROVAL_ID --digest EXACT_REVIEWED_DIGEST
python -m personal_agent resume TASK_ID
python -m personal_agent show-evidence TASK_ID action:ACTION_ID --project example
```

For an owner revision, pause using stop, recover, prepare a JSON proposal following
`spec/examples/plan-revision.json` with the **current** digest from `show`, then run
`revise TASK_ID --plan PROPOSAL.json`, clear-stop and resume. Copy every retained node's ordinal,
action ID, request and dependencies exactly; append fresh ordinals. Pending approved or verified
actions cannot be removed or changed, approvals cannot be reset, and uncertain effects must be
reconciled first. Alternatively set `mode: "append"` and provide only NEW steps with the current
base_digest; trusted code preserves all saved steps without copying large create arguments.
The model uses this compact format at an execution checkpoint; it cannot change the saved base.
The saved initial plan remains in v1 format for migration compatibility; history records the
new active snapshots. A no-op, stale, cyclic or substituted plan is rejected transactionally.

Windows pins ancestors without delete/write sharing. On Linux the owner explicitly selected a
trusted environment: do not move the application/project roots during execution. Linux creates
only direct children of the project root; nested output paths are denied before dispatch.
Landlock ABI 3+, O_TMPFILE and procfs are required. There is
no unsafe fallback on unsupported filesystems. See [full boundaries](m1-completion.md).

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

Make and verify a backup before schema upgrades. Version 2 added plan revisions; version 3 adds
approval-preview ownership/expiry inventory and support for terminal partial (ADR-022);
legacy plans, evidence and approvals are preserved. Directory identity bindings deliberately
become invalid after physical relocation: use a fresh create task and approval in the new root.
Migration is transactional;
newer unknown schema versions are rejected. Rollback restores a backup with matching code,
not a destructive down migration. A G: backup is not disaster recovery; retain an encrypted
off-disk copy separately.
# M1 data admission update

Read [current security boundaries](m1-security-boundaries.md) before using private sources.
`--allow-file` is an explicit internal-file local-context grant, not a secret-free certificate.
Use `--allow-private-file relative.txt` for an exact private file authorized for local tool
IPC, canonical evidence and Ollama; private summaries are withheld from task diagnostics.
`--include-private` grants project-scoped private memory locally. Never provide real secrets:
recognizable credential patterns are denied, but arbitrary/encoded secrets are not detected
universally. No remote egress is enabled by these flags. Secret denials block the task;
inspect the source under owner control and create a correctly scoped task instead of changing
policy from model/source text. Existing tasks and complete saved evidence are not rewritten.
