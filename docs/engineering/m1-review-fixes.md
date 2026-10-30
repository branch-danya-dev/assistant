# M1 review remediation — PR #5 remains stacked on PR #4

**M1 is `in_progress`. REQ-017 and REQ-019 remain `specified`, P0, target M1.**
Their original acceptance is unchanged. A working closed tool registry and local-only model
adapter do not establish universal injection resistance or secret prevention. TASK-026 is
reopened; TASK-009/010/041 retain implementation evidence but await that security dependency.
TASK-044 explicitly retains the remaining P0 gate. SCN-007 is specified with partial evidence.
CI now rejects a completed milestone with an open P0 requirement or task.

Review: [5717718719](https://github.com/branch-danya-dev/assistant/pull/5#pullrequestreview-5717718719).
Starting HEAD: `c4a52196019c3ed9cce573139b4a34dfd0386110` (all four existing PR #5 commits retained).
Base: `feat/m0-m1-local-agent`, `42a9f31dd1556a1714d64d86ee6e8f630b027d2f`.
Neither PR is merged/retargeted; main is unchanged.

## Bounded context and truthful outcomes (TASK-045, SCN-012)

The file limit remains **32,768 UTF-8 bytes**. Complete read results stay in SQLite
`actions.result`; complete proposed create bytes stay in saved requests/plan history. Final
LLM context is a separate projection, measured after nested JSON serialization against the
unchanged 6,000-byte message limit. Each read/memory result is included in full or replaced
by an explicit `receipt_only` view: action reference, saved-result digest, bytes/SHA-256 or
record receipts. There are no source excerpts or hidden truncation. The model is told which
content it did not receive; each final checkpoint records coverage and projection digest.
`show-evidence` remains a scoped metadata view of saved evidence, not a new file read.

Final context contains a plan digest, revision count, next ordinal and last dependency ID,
not repeated create text. `revision.mode=append` carries only new steps. Trusted code retains
the exact saved base transactionally, enforcing stale-digest checks, immutable IDs/requests,
dependencies, one-use approvals and no duplicate create targets. Full owner replacement
proposals remain supported. At most three revisions and 40 lifetime action IDs still apply.

When source content is withheld, trusted finalization discards model semantic claims and
reports terminal **`partial`**, CLI exit **2**, with all verified action references and an
explicit notice that full analysis is incomplete. Even receipt overflow has this bounded
fallback; it makes no final model call and does not repeatedly pause for context exhaustion.
An exact approved create can complete with a deterministic bytes-verification receipt only;
this never claims semantic correctness of the file. For fully supplied small reads, model
prose remains explicitly unverified. A paused task resumes from saved evidence, without
re-reading changed files or replaying verified creates.

The owner can inspect original files against saved receipts, or prepare smaller sources for
a new explicitly scoped analysis task. No automatic chunked/full-document analysis is claimed.
Initial oversized owner intent/persona/scope still fails before execution, visibly; the model's
1,024-token output limit is unchanged and does not promise generation of arbitrary 32 KiB text.
Large create argument tests use synthetic providers/owner-supplied plans, not a Qwen capacity claim.

## Private approval previews (TASK-046, SCN-013)

Previews live in `cache/approval-previews-v1`, under the single application root. Files have
POSIX mode 0600 in a 0700 current-user directory, or an atomically created Windows protected
DACL granting full control only to the process-token user. The owner SID, one allowed ACE,
protection against inheritance and file type/link count are checked through opened handles
before any proposed bytes are written. ACLs are not repaired on an untrusted existing object.
No privileged account configuration or extra package is required.

The cache parent chain rejects symlinks/junctions. Windows pins ancestors and deletes the
verified file by handle. Linux uses no-follow directory-relative operations inside the private
directory; as in ADR-021, malicious same-user/root relocation is outside the boundary.
Administrators with take-ownership powers and malicious processes of the owner are not isolated.

Each preview is registered by random name, file identity and expiry **before writing content**.
The TTL is **900 seconds**, maximum serialized size **256 KiB**, maximum tracked files **64**.
Creation cleans expired entries first. `cleanup-previews` repeats cleanup deterministically
after restart; only registered, expired, still-identical regular private files may be removed.
Unexpected objects are skipped and counted. Foreign/unregistered files are never swept by a
glob. Size/cap/permission failures are payload-free. Failed writes attempt handle-safe removal;
if removal fails, the registered partial file expires immediately for a later cleanup.

Expiry means eligibility for cleanup, not a daemon deleting bytes at that instant. Without a
subsequent preview or `cleanup-previews`, files remain on disk. Legacy unregistered `cache/approval-*.json`
from older versions require explicit owner inspection/removal; automated cleanup does not
guess ownership. Ordinary deletion is **not cryptographic erasure**, and does not erase
canonical journal contents or backups. CLI stdout contains location/digest/expiry, never the
full proposed content. This is a bounded privacy fix, not completion of REQ-019.

Windows API contracts: [NtCreateFile](https://learn.microsoft.com/en-us/windows/win32/api/winternl/nf-winternl-ntcreatefile),
[GetSecurityInfo](https://learn.microsoft.com/en-us/windows/win32/api/aclapi/nf-aclapi-getsecurityinfo),
[SetFileInformationByHandle](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-setfileinformationbyhandle).

## Migration and evidence provenance

ADR-022 extends the lifecycle with terminal `partial`. SQLite v3 adds only the preview inventory;
v1/v2 action IDs, complete results, plan digests, approvals and consumption state are preserved.
Tests cover v1 and v2 pending-approval migration and exactly-once continuation. Older binaries
reject v3 instead of misinterpreting the new state. Back up with the existing online backup
before upgrading; rollback restores the backup with matching code, never manual version edits.

Historical `windows-m1-completion.json` is retained as recorded. Its old check named
`live_create_approval_revision_exactly_once` means **real Qwen planning/final responses plus
an owner/test-harness injected revision**. It is not proof that live Qwen generated a revision.
The current verifier uses an unambiguous check name, records this provenance and records
source commit/dirty state alongside the runtime fingerprint. Synthetic providers separately
exercise model-generated revisions; a regression verifies that the harness cannot certify
live model revision just because its own injected revision succeeded.

The current check results, exact tested commit, host report and CI links are in
[m1-review-validation.json](evidence/m1-review-validation.json). Historical reports apply only
to their original fingerprints/commits, not automatically to these fixes.

## Subsequent integration, only on owner instruction

1. Review and integrate PR #4 first.
2. After that, separately authorize retargeting PR #5 to main. If #4 is squashed, carry only
   PR #5's original four commits and its new remediation commits onto the resulting base.
3. Recheck the complete remaining diff and run Windows/Ubuntu CI on the resulting HEAD/base.
   Retargeting/rebasing does not close REQ-017/019 or the M1 gate by itself.
4. Merge PR #5 only after owner review and explicit instruction; back up production state
   before deployment, then run recovery/doctor and a synthetic host check.
