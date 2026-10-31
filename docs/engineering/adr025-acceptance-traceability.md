# ADR-025 acceptance revision and integration gates

2026-10-31. **Policy accepted; M1 remains in_progress.**
[Owner decision source/date](adr025-owner-decisions.md): OD-1/2/3=YES.
This decision/traceability layer starts at PR #8 `ee7dbdd871306451a1ea9b44715ac7f3689b192e`,
base `feat/m1-trust-inventory`. No runtime code, production state, grants or model settings
change. ADR-026/027 remain accepted; their original text is historical and acceptance_update
points to the later ADR-025 approval.

## Explicit acceptance revision

`spec/requirements.json` retains each original `acceptance` verbatim:

- REQ-017: “Webpage, document and message instructions cannot escalate privileges or override owner policy.”
- REQ-019: “No secrets in prompts/logs/repo; unauthorized cloud egress rejected.”

Both remain **P0, target M1, specified**. Their added `acceptance_policy` explicitly governs
bounded M1 evaluation. It does not reinterpret the original text as already passed.
TASK-044/026 preserve their original criteria and link the same policy; M1's exit gate points
to it. Implemented M1 boundaries and mandatory actual-adapter acceptance at M2-M4 are
separate. An untested supported M1 boundary is not postponed to a later stage.

The complete enumerations are `spec/m1-data-contract.json` sources and sinks. Sources are
owner intent/scope, UTF-8 names/bodies, memory/provenance, persona, registered tool output,
model steps/revisions and saved legacy results. Sinks are loopback Ollama, worker IPC,
journal/evidence, diagnostics and private previews. Explicit private grants cover only
journal/worker/Ollama/preview for the owner task; diagnostics exclude private payloads.
Unknown sources/operations fail closed. CAP-001/003-008 cover the implemented runtime;
CAP-002's lexical scope remains partial and does not claim semantic retrieval.

## Evidence coverage and limits

| Gate / traced scope | Executable evidence under tests/ | What it does not prove |
| --- | --- | --- |
| REQ-017: source data never grants authority | test_injection_boundary.py, test_security.py, test_models.py: actual file/memory retrieval, persuaded synthetic provider, closed intent/registry | Every real Qwen response or any absent adapter |
| REQ-019: classifications, credentials, local sinks | test_data_boundary.py, test_trust_inventory.py: admission/inventory before persistence/IPC/model/preview; private grants, closed diagnostics, numeric loopback | Unknown-secret discovery; unrelated Git clients; hostile same-account process |
| Legacy and durable evidence | test_trust_lifecycle.py, test_memory_admission_search.py: ID/hash review, renewal, provenance, expiry, revocation, FTS, immutable authority | Automatic legacy classification; complete owner inventory; physical erasure |
| Approval and bounded audit | test_release_remediation.py: atomic active admission/approval binding, payload-free ACK, unchanged DB on denial, overflow | Same-account DB integrity or unlimited audit; truncated output is incomplete |
| Recovery/revisions | test_m1_create.py, test_journal.py, test_plan_revisions.py, test_bounded.py: synthetic filesystem effects, subprocess crash, no replay, exact approvals | Live model-generated revision or real external send reconciliation |
| Host aliases / SCN-009 | test_file_aliases.py, test_previews.py, test_storage.py: ordinary Windows case/Unicode/hardlink/ACL; Linux trusted-root flat-create/Landlock | Two real 8.3 checks skip without aliases; case-sensitive-directory positive/failure queries are injected |

`tools/verify_package.py` checks the installed wheel outside checkout.
`tools/installed_acceptance.py` requires child exit 0 and explicit passed=true for smoke and
read/search workflow. Historical reports do not certify a new HEAD; read/search smoke is not
full M1 semantic/security acceptance, live mutation/revision or model-blob verification.
Full discovery remains required: schema/JSON fixtures, traceability, combined acceptance DAG,
regression, security, crash, HTTP integration; Ruff, wheel and outside-checkout execution on
Windows/Ubuntu. A skip is an uncovered platform case, never a pass.

**Residual risks retained:** owner misclassification; incomplete inventory; unknown/opaque/
encoded secrets; same-account code or DB access (trusted, not an isolation boundary);
backups and canonical retention outliving projection authorization; no secure-erasure promise;
real 8.3 and case-sensitive-directory gaps; future real connector behavior. Backups must be
protected and restoration tested for the selected code/schema pair. Expiry/retrieval removal
neither erases historical DB/backup bytes nor silently renews admission.

## Independent and historical evidence

- PR #8 `ee7dbdd871306451a1ea9b44715ac7f3689b192e`:
  [CI 41208680692](https://github.com/branch-danya-dev/assistant/actions/runs/41208680692),
  Windows 193 passed / 5 skipped, Ubuntu 187 / 11, 198 total;
  [independent review](https://github.com/branch-danya-dev/assistant/pull/8#pullrequestreview-5723463751)
  confirms approval/audit/harness fixes. It did not independently inspect local package
  hashes or the live owner-host session.
- PR #9 `a2f4c1939dbcb410bb50cc29265bb6100629659e`:
  [CI 41210234968](https://github.com/branch-danya-dev/assistant/actions/runs/41210234968),
  Windows 213 / 5, Ubuntu 207 / 11, 218 total;
  [experimental review](https://github.com/branch-danya-dev/assistant/pull/9#pullrequestreview-5723463853).
  Trailing-newline numeric-schema hardening and broader live acceptance remain. TASK-011/
  CAP-009 there stay in_progress/experimental with explicit opt-in. This #8-based branch
  retains todo/planned because it lacks that implementation; it neither overwrites #9
  nor imports/accepts M2 automatically.

**Decision checkpoint:** [41218755051](https://github.com/branch-danya-dev/assistant/actions/runs/41218755051)
checks `9db7de41f1e96f5e2c694f83f71d133d3aab6993` directly on both platforms: Windows
197/202 passed (5 skips), Ubuntu 191/202 (11 skips), all stages successful. Fresh installed-wheel
Qwen smoke/read-search passed on that clean checkout. [Structured evidence](evidence/adr025-decision-checkpoint.json)
records exact scope, local staged-tree distinction, wheel digest and the unchanged-runtime review
used to close TASK-050. Final metadata-only HEAD must be reported and verified separately.

These are historical exact-SHA results. Fresh decision-PR HEAD, CI counts/skips, local wheel
digest and selected-Qwen result belong to the new PR's validation record/body and delivered
report; older evidence is not relabelled current. #8's review is not independent review of
this new policy/traceability diff.

## Completion audit

| Record | State | Exact remaining acceptance |
| --- | --- | --- |
| ADR-025 / OD-1/2/3 | accepted / YES | No repeated owner decision needed |
| TASK-049 | done, unchanged | Historical bounded implementation; not M1 acceptance |
| TASK-050 | done | All own criteria and TASK-049 dependency satisfied at the exact-SHA checkpoint below; no M1 closure implied |
| TASK-044 | in_progress | Actual 8.3 alias and real case-sensitive-directory rejection evidence, final bounded coverage review, current platform/model results; TASK-049/050 done |
| TASK-026 | in_progress | Open TASK-044 acceptance dependency; re-evaluate scoped memory/egress under policy |
| TASK-041 | in_progress | TASK-026 dependency; retain renewal/retention/backup limits |
| TASK-009 | in_progress | TASK-026/041 dependencies; SCN-004/005 evidence does not bypass them |
| TASK-010 | in_progress | TASK-009 dependency; working CLI is insufficient |
| REQ-017/019; SCN-007; M1 | specified; specified; in_progress | Bounded security gate open; no automatic status promotion |

TASK-044's work dependencies TASK-004/005 and TASK-049's prerequisites are done. Added
TASK-050 acceptance dependency creates no return edge: TASK-050 depends only on TASK-049.
Closure order: TASK-050 (own evidence), then TASK-044 -> TASK-026 -> TASK-041 -> TASK-009 ->
TASK-010. Other TASK-009 prerequisites TASK-005/006/007/008/025/029 are done. Combined work
and acceptance graph must stay acyclic. Policy approval or a green subset cannot close it.

## Actual adapter gates at M2-M4

`spec/connector-gates.json` keeps nine adapters disabled with null actual evidence/owner
enablement. Each has task-specific `functional_checks`, nine mandatory security checks and
an evidence policy. Schema and task acceptance require both functional/security results
before completion/enablement. Unsupported mutation must prove denial rather than skip
approval/uncertainty checks. Read evidence cannot certify a write adapter or another account.

M2 document/spreadsheet/browser: actual parsers, reopened artifacts, formulas, hidden/embedded
content, links/downloads and provenance. M3 browser mutation/email/bot/cloud: actual origins,
accounts, recipients, dataset/purpose, credential isolation, one-use approvals and uncertain
effects. M4 desktop/voice/personal Telegram/calendar: actual UI/session/account boundaries,
authentication, target identity and reconciliation. Synthetic M1 stubs prove denial only.
Real vault/credential tests require separately authorized implementation and test accounts.

## Integration plan — NOT EXECUTED

Remote state refreshed on 2026-10-31 before editing:

| PR | HEAD | Current base |
| --- | --- | --- |
| #4 | `42a9f31dd1556a1714d64d86ee6e8f630b027d2f` | main at `c1a0079d81b4b641568536ef8bc6d16ea8d65c22` |
| #5 | `62df23f2e49c6f90134d6d7ad46c7fc284d77696` | feat/m0-m1-local-agent |
| #6 | `d89cb03be69a291ec249e2776de4198f4cce8940` | feat/m1-safe-create-revisions |
| #7 | `e9c0fb300605ed77de208e8179a3746e9c790883` | feat/m1-security-boundaries |
| #8 | `ee7dbdd871306451a1ea9b44715ac7f3689b192e` | fix/m1-file-alias-boundaries |
| decision PR | new descendant of #8; exact HEAD in PR | feat/m1-trust-inventory |
| #9, separate | `a2f4c1939dbcb410bb50cc29265bb6100629659e` | feat/m1-trust-inventory |

Future order: **#4 -> #5 -> #6 -> #7 -> #8 -> decision PR**, with **merge commits preserving
ancestry**, #9 separate. No merges/rebases/retargets, existing branch writes, main/deploy or
production backup operations occur now.

Before **each** future merge, prepare current HEAD/base/merge-base, own delta/conflict check,
exact-head Windows/Ubuntu CI plus proposed-base integration checks, review disposition,
backup/restore evidence and rollback to matching code/schema (including pending approvals
and uncertain actions). Request separate explicit owner consent for that exact merge.
Preserve branch refs while dependents exist. Each subsequent base change also requires
separate consent, renewed diff/CI/review, then a separate merge decision. Avoid automatic
base-branch deletion (GitHub can retarget dependents); inspect bases after every action.
Integration approval never implies deployment or production migration approval.

Historical independent `integration-independent.json` was reread locally; SHA256
`10340cb1465b4f7e21c8f8735dd9923ffacc6fe383ec6748be281ae24f0026e4`. Its object-only negative
experiment squashed #4's tree onto main as synthetic `a7d68fad11d05cf748cad70f84570ca13558bc25`,
then compared original #5: exit 1, **22 conflicting paths**, merge-base old main. Squash loses
#4's original ancestry. This is historical evidence for unchanged #4/#5, not an integration
executed here or a prediction of every future conflict count. No squash/rewrite is planned.

**#9 consequences:** its only parent is #8 `ee7dbdd...`; the decision branch is a sibling
descendant. Merge commits carry that ancestor into future main. Integrating the decision
layer neither copies it into #9 nor rewrites #9's parent. With the #8 base, #9 still shows
its experimental delta. A later, separately approved retarget to main must inspect the
actual merge-base/combined result, reconcile shared specs retaining accepted ADR-025, and
rerun all tests/review. A three-dot diff can omit main-only decision changes: review the
proposed integration result too. Squashing lower layers loses ancestry and may reintroduce
their history/conflicts. No force-push, rebase, retarget or automatic calculator acceptance.
