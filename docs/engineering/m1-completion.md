# M1 completion candidate — stacked on PR #4

Base audited and rechecked: `42a9f31dd1556a1714d64d86ee6e8f630b027d2f`,
`feat/m0-m1-local-agent`. PR #4 stays open; neither PR is merged by this work.
Final milestone status is gated on the recorded checks below, not this document's title.

## Implementation and security evidence

| Change | Executable evidence |
|---|---|
| TASK-009: in-task model/owner revisions, explicit dependencies, immutable action IDs/ordinals/requests, three revision limit, 40 lifetime IDs, compare-and-swap digest | `tests/test_plan_revisions.py` |
| TASK-010: CLI states, saved action evidence, project/ref checks, bounded metadata projection, mandatory complete evidence set | `tests/test_cli.py`, `tests/test_evidence.py` |
| TASK-043: exact owner create allowlist, independent one-use approval, create-only UTF-8 <=32 KiB, no overwrite/truncate/delete adapter | `tests/test_m1_create.py` |
| Independent re-observation never calls execute; one create dispatch and one approval consumption | `test_real_create_exactly_once_and_side_effect_free_verify` |
| Timeout, task budget, stop, task-local cancellation, parent process death terminate the worker tree | `tests/test_bounded.py` |
| Windows directory-handle chain denies write/delete sharing; rejects reparse points, ADS, hardlinks and replacement of approved parents | `tests/test_m1_create.py`, `tests/test_security.py` |
| Linux trusted environment: flat new-file names only, no-follow dirfds, anonymous O_TMPFILE, exclusive linkat publication, layered Landlock | `test_linux_nested_create_is_denied_before_dispatch`, `test_linux_kernel_denies_root_moved_out_after_open_before_publish` |
| Real crash after create before journal acknowledgment becomes needs_reconciliation, with no automatic replay | `test_real_crash_after_create_before_ack_never_replays` |
| Actual model manifest/blob existence, canonical opened-handle containment, sizes and SHA-256; separate Ollama tag/FROM assertions | `tests/test_host_evidence.py`, `tools/verify_host.py` |

SCN-004/005/007/009/010/011 retain the original runtime tests and add the concrete create,
revision, evidence and process-failure fixtures above. No messages, purchases, installation,
privileged operations or self-registered tools are implemented. No model comparison occurs.

## Process and filesystem boundaries

Tool execution **and** observation share a five-second wall deadline. The parent polls stop
and cancel every 25 ms and also caps the deadline by the persisted task budget. Ollama calls
use the same disposable worker mechanism with a 60-second cap and absolute HTTP deadline.
Windows assigns a suspended worker to a kill-on-close Job before it runs; the two-process
limit accommodates Python's venv redirector. Linux sets PDEATHSIG and checks the startup race.
There are no abandoned execution threads and no automatic non-idempotent retries.

Kernel or failing-device I/O can be uninterruptible. A failed one-second kill confirmation
sets persistent stop; uncertain mutation stays blocked for reconciliation. Stop cannot undo
already-created bytes. On Windows atomic exclusive creation may leave a partial new file if
killed during write; the task never reports it verified and never truncates/recreates it.
Linux publishes a fully written anonymous inode without replacement; missing O_TMPFILE,
Landlock ABI 3+, procfs, supported syscall architecture or required rights causes refusal.

**Owner-confirmed Linux mode (ADR-021): trusted environment.** Windows is the primary target.
The application home and project-root directory identities on Linux are trusted anchors;
another process with the owner's credentials must not move them during execution. Pinning
a Linux directory fd does not prohibit its rename. Linux creates are therefore limited to
**direct children of the trusted project root**; nested create paths are rejected before dispatch.
This avoids ambiguous in-project parent renames as well as out-of-tree replacements. Landlock
also denies publication if the root is moved outside the app home. This is not a sandbox against a hostile owner, root, debugger,
database editor or kernel. Windows pins the entire ancestor chain for the filesystem call.

The verifier checks content hash, length, file identity and independently reopened bytes.
Evidence proves the observation at that time, not permanent immutability against later edits.

## Storage and compatibility

SQLite schema v2 adds only `plan_revisions`; tasks, action IDs, evidence, approvals and the
v1 `tasks.plan` remain intact. Legacy plans are interpreted as explicit sequential dependencies.
The migration/CLI test resumes a v1 pending approval without resetting its digest or action ID.
Take the existing online database backup before first opening production state with v2.
Rollback means restoring that backup with matching v1 code; no destructive downgrade exists.
After physical root relocation, old create directory bindings deliberately fail closed: create
a fresh owner-scoped task and approval. Already verified evidence/history remain readable.

Plan retirement can remove only never-attempted, unapproved pending actions. Retired IDs are
never recycled, verified/approved actions cannot be removed, and new creates cannot replay a
previously prepared effect target. Invalid revisions leave the previous plan and approvals
unchanged and produce a visible refusal. Existing approvals are never silently renewed.

## Evidence view and privacy

`show-evidence TASK_ID action:ACTION_ID --project PROJECT [--limit 256..32768]` reads the
saved verified result, not the current source file. It requires task/action/project agreement
and the original task scope. Output uses a structural allowlist: path, size, SHA-256, identity,
record IDs/sensitivity and digests. It deliberately withholds arbitrary file text, memory
statements and source strings rather than pretending a regex detects every secret. `show`
includes these receipts and plan history; its event view is limited to the latest 100 events.
Owner/model prose uses bounded best-effort credential redaction. Generic secret detection,
vault integration, and factual verification of generated prose are still not claimed.
For concrete approval review, `approval-preview APPROVAL_ID --project PROJECT` exports the
exact request and scope into a new private cache JSON file; stdout contains only its location
and bound digest. This keeps reviewable proposed content available without dumping it into logs.
All CLI responses also have a 64 KiB cap with explicit truncation.

## Validation record

Current host acceptance passed with real selected Qwen, including create/approval/revision,
independent hashes and persisted evidence in an isolated synthetic runtime. The owner's
production database was not opened/migrated. See [host report](evidence/windows-m1-completion.json).
The report fingerprints runtime source, schemas, model/storage configuration and the verifier.

Final CI/package result links are recorded here before M1 status is advanced. The first Ubuntu
run exposed O_TMPFILE's retained anonymous `/proc` name; independent published-name/inode
verification corrected that and subsequent Ubuntu CI passed. Host checks also discovered the
local Ollama retained-original-manifest format; the verifier now hashes the retained original
and checks its agreement with all active layers, not merely the tag's filename.

API references: [Windows relative FILE_CREATE and sharing](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/ntifs/nf-ntifs-ntcreatefile),
[Linux O_TMPFILE publication](https://man7.org/linux/man-pages/man2/open.2.html),
[Landlock rights and limits](https://www.kernel.org/doc/html/latest/userspace-api/landlock.html),
[Ollama manifest implementation](https://github.com/ollama/ollama/blob/main/manifest/manifest.go).

## Integration order

1. Review and explicitly accept PR #4 as the foundation.
2. Merge PR #4 only on the owner's instruction.
3. Retarget this stacked PR from `feat/m0-m1-local-agent` to `main`; if #4 was squashed,
   rebase only the new commits onto its resulting main commit and rerun CI.
4. Review the remaining diff, back up the database, and merge this PR only on owner instruction.
5. Run recovery/doctor and synthetic host acceptance before using new create permissions.
