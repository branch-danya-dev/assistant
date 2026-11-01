# TASK-044 final security acceptance cycle — 2026-11-01

Baseline: PR #10 `4d033408b041add4c4d0865dab2c5fe662302890`, branch
`docs/adr025-accepted-traceability`; main `c1a0079d81b4b641568536ef8bc6d16ea8d65c22`.
PR #4–#10 heads and bases matched the supplied checkpoint. This is one new stacked
draft; existing refs, production data, OS/Ollama configuration and models are untouched.
ADR-025 remains accepted, OD-1/2/3 YES, TASK-050 done. Original P0 criteria and M2–M4
actual-adapter gates are preserved. This implementation-side coverage audit does **not**
claim a new independent reviewer sign-off; that disposition remains required.

## Confirmed defect and regression

`Identity.save` checked a private inventory mark only during receipt creation, after
publishing the new persona file. A reviewed private mark for version 2 therefore caused
`inventory_source_denied` but left `persona-2.json` on disk; subsequent `current()` failed.
The new regression failed on this exact leftover file before the fix. Persona's API
supports internal admission only; now the private mark is denied before any new file.
No authority, schema, migration or data-classification policy is changed.

The dormant real-short-name regression also needed its legacy setup updated for v4:
an altered source has a stale receipt and must first fail `source_review_required`.
It now explicitly reviews exact synthetic legacy bytes by ID/digest, then checks the
alias denial without changing scope, prior evidence or dispatch count. This is a test
correction, not permission to bypass admission in production.

## Traceable source → policy → sink coverage

All entries below use synthetic payloads. `tests/` prefixes are omitted. Results must
be paired with the exact-SHA run in the PR, not inferred from this matrix's existence.
Model persuasion is deterministic fault injection; the filesystem, SQLite, worker
processes and loopback HTTP fixtures exercise actual adapters.

| M1 source | Ingress / authoritative policy | Sinks exercised | Executable regression | Observed denial / evidence | Residual |
|---|---|---|---|---|---|
| Owner intent and scope | `Journal.create`, `validate_scope`, `admit`, task receipt | SQLite, IPC, model, CLI | `test_final_acceptance`: credential intent/filename; hostile persona/intent; `test_trust_inventory`: private sink grants | Credential intent rejected before SQL/worker; persuaded CAP-999 blocked with no action; scope unchanged | Owner classification can be wrong |
| UTF-8 names and bodies | Exact file grants, inventory, pinned handles, `file_access`, whole-result admission | Worker IPC, journal/evidence, model, diagnostics | `test_file_aliases`; `test_data_boundary`: nested credentials and whole-file classes; `test_injection_boundary`; `test_final_acceptance`: filename revision | Alias/restricted/credential denial; no unauthorized dispatch; approved reads remain attributed evidence | Actual NTFS capability results below; unknown encoded secrets not detected universally |
| Memory + provenance + FTS | Canonical whole-record receipt, project/class/expiry filters before ranking, independent verification | SQLite/FTS, child worker, model, CLI | `test_memory_admission_search`; `test_trust_lifecycle`; `test_final_acceptance`: provenance revision | Foreign/private/revoked/tampered data omitted; bounded exhaustion explicit; hostile source ref cannot grant CAP-999 | Physical old DB/FTS/backup bytes may persist; lexical retrieval only |
| Persona | Owner version API, metadata inventory before publication, receipt on read | Identity files, model user context, CLI | `test_final_acceptance`: private inventory persona and hostile persona; `test_trust_inventory`: legacy persona review | Private-marked version leaves no file; hostile persona remains data, cannot register tool; missing receipt denied | Trusted owner/code; no private-persona feature |
| Registered tool output | Closed registry/output schema, independent observation, inherited task classification | Worker IPC, journal/evidence, model, diagnostics | `test_data_boundary`: authoritative result fields; `test_injection_boundary`; `test_security`: verifier | Extra role/approval/verified fields denied; changed observations rejected; source text never authority | Trusted same-account registry/DB; model prose remains unverified |
| Model steps and revisions | Reply schema, registry, immutable plan digest/dependencies, exact approval | Saved plan/actions, workers, previews, CLI | `test_plan_revisions`; `test_final_acceptance`: unknown capability and private create; `test_release_remediation` | No scope expansion/replay; unauthorized create waits; changed/reused approval denied; private ACK payload-free | Live model-generated revisions not certified by a synthetic provider |
| Legacy saved results | No migration attestation; explicit ID/digest owner review, current dependencies | Model/IPC, journal, diagnostics, preview | `test_trust_inventory`: legacy resume/verified create; `test_trust_lifecycle`: changed result/renewal; real-short legacy regression | Missing/stale admission denied; review preserves grants, evidence and one-use consumption | Review assumes accurate owner classification; trusted DB |
| All admitted sources → Ollama | Numeric loopback, no redirects/proxies/cloud fallback; task/persona/result admission before send | Real loopback HTTP adapter | `test_models`: egress/redirect/protocol/deadline; `test_data_boundary`: non-loopback recheck | External hosts and redirect rejected before unauthorized connection; malformed replies closed | Other same-account programs are outside this boundary |
| Private data → owner approval | Exact action digest + current task admission + protected preview ACL/TTL | Preview file, approval journal, stdout/stderr | `test_final_acceptance`: private create end-to-end; `test_release_remediation`; `test_previews` | Explicit preview contains exact synthetic payload; CLI/ACK withhold it; approval consumed once | TTL cleanup is on demand, not secure erasure |
| Interrupted/expired sources | Persistent stop, reconciliation, explicit renewal and inventory recheck | Journal, FTS, worker, diagnostics | `test_bounded`, `test_journal`, `test_m1_create`, `test_trust_lifecycle` | No uncertain mutation replay; renewal preserves stop/consumption; audit payload-free | Backup/restore requires matching code/schema and separate production authorization |

## Windows capability procedure

Owner host probe: non-elevated token; Hyper-V commands absent; read-only volume 8.3
query returned access denied; WSL inventory exceeded 12 seconds. No local VHD/VM was
assumed available and no host settings were changed. Ordinary synthetic filesystem
tests still exercise real case aliases, Unicode, hardlinks, junctions and ACLs.

`tools/windows_ntfs_acceptance.ps1` is executable only on a GitHub-hosted disposable
Windows runner. It creates its own 256 MB VHD, formats only that image, assigns an
unused drive, verifies NTFS/label, changes **only this VHD's** 8.3 setting, runs bounded
synthetic tests and detaches the exact image in `finally`. No global 8.3 setting changes.
`ASSISTANT_TEST_ROOT` redirects test fixtures only; application storage defaults are unchanged.

`test_windows_ntfs.py` additionally requires the hosted-runner guard and VHD marker.
It enables the actual flag only on its disposable test directory and proves distinct
`Name.txt`/`name.txt` objects before claiming real case-sensitive coverage. It checks
creation, direct observation, create-parent snapshot, child worker, saved-task execution
and a late flag change after approval (no consumption or file creation).
Failure to enable is an explicit skip with command exit, never simulated success.
Existing injected flags/query-failure tests remain labelled simulated.

At checkpoint `df0b0e140a2062076ca737542f1f14921dd6e82f`,
[exact-head push CI](https://github.com/branch-danya-dev/assistant/actions/runs/41261249205)
passed all stages. Windows: **202 passed / 7 skipped / 209 discovered**; Ubuntu:
**196 / 13 / 209**. Windows ordinary-root skips are two missing 8.3 aliases, two VHD-only
case tests, and three Linux-only tests. Ubuntu's 13 skips are Windows-specific.
The separate VHD run passed **34 / 3 / 37**: both real 8.3 tests and both actual case-mode
tests passed; only three Linux-only cases skipped. The log records volume state 0,
successful per-volume enablement, actual case-sensitive enable/query exit 0 and successful
VHD detach. Ordinary case aliases, Unicode/collision, hardlink and junction checks passed
on the real VHD too. Injected unknown/case flags remain simulated evidence, separately.

The final child adds absolute opened-name assertions and directory-alias worker/read/legacy
checks. Its exact final SHA/CI results belong to [PR #11](https://github.com/branch-danya-dev/assistant/pull/11)
and the delivered report; this checkpoint is not silently relabelled as the final run.

Provisioning syntax follows Microsoft's [per-volume 8.3 command](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/fsutil-8dot3name)
and [per-directory case sensitivity](https://learn.microsoft.com/en-us/windows/wsl/case-sensitivity).
No change to host-wide NTFS settings was needed.

## Fresh installed-wheel Qwen and package evidence

The checkpoint wheel SHA256 is
`d7f0b14fa63a378a930cab60098be273002d4aaf41efe5c4395ed5ddf90dea93`.
Local Windows schema/DAG, 209-test discovery (202 pass/7 skips), Ruff and outside-checkout
installed-wheel checks passed. Dependencies were reused locally; no model was downloaded.
`tools/installed_acceptance.py` passed both smoke and read/search gates with child exit 0
AND explicit JSON `passed=true`, from a fresh installed environment outside checkout.

The additional reproducible `live_extended.py` in the delivered evidence bundle passed
12 checks at 2026-11-01T01:31:56Z. Live Qwen proposed two exact synthetic create requests;
the owner/test harness approved only equality with the expected full request/digest.
One create was verified, paused by the harness and resumed after reopening the store:
completed with one attempt. The other process exited 17 after actual create but before
acknowledgement; recovery produced `needs_reconciliation`, refused replay, independently
observed exact bytes/hash, then recorded owner/test-harness `applied` reconciliation.
The reconciled action remained non-replayable (task blocked, not misreported completed).
Both approvals consumed once; both 23-byte file hashes matched. The harness and evidence
hashes are in [structured checkpoint evidence](evidence/m1-final-security-checkpoint.json).
Pause/crash injection and reconciliation are test-harness actions, **not model-generated
revisions**. Tool receipts/file observations are verified; model prose remains unverified.
No production DB, credentials, model settings or model-blob verification was involved.

## Acceptance disposition

The owner explicitly chose on 2026-11-01 to **leave independent review as an open gate**.
TASK-044 remains **in_progress**: actual NTFS and current platform/model checkpoints now
have evidence, but final independent bounded coverage review is still required. No
reviewer identity or approval is invented. TASK-026 → TASK-041 → TASK-009 → TASK-010
remain in_progress; REQ-017/019 and SCN-007 specified; M1 in_progress. TASK-050 stays done.
No absent connector, vault, M2 calculator or wider M2–M4 feature is accepted here.

Residuals: incomplete inventory, misclassification, unknown/opaque/encoded secrets,
trusted same-account code/DB, retention/backups and disabled future adapters. Accepted
ADR-025 policy is not universal detection or security completeness. Future integration
still follows #4→#5→#6→#7→#8→#10 via merge commits, #9 separate, with refreshed exact
SHA/base/diff/CI/review/backup/rollback and separate owner consent for each merge/base
change. This new child also requires its own review and explicit integration disposition.
Historical squash #4 caused 22 conflicting paths with original #5; no integration is
performed by this cycle.
