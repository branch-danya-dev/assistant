# M1 bounded data admission and metadata inventory (ADR-026 / TASK-049)

This is an incremental implementation from PR #7 `e9c0fb3`, not M1 acceptance.
ADR-025 remains **provisional**. REQ-017/019 remain **specified, P0/M1** with original
acceptance unchanged. TASK-044/026 and M1 remain **in_progress**. The owner authorized
implementing option B; that is not a recorded vote on the three acceptance decisions.
See [owner decision procedure](adr025-owner-decisions.md).

## Exact supported contract

Canonical inventory: `spec/m1-data-contract.json`. Trusted boundaries are the local owner
CLI/API, reviewed code, canonical database, and OS primitives. There is no protection
against a malicious process with the same account modifying code/database/admission receipts.
All model/source text remains data, including persona, provenance and nested JSON.

| Source | Admission before content transport/persistence |
| --- | --- |
| Owner intent and scope | `Journal.create` is an owner-only attestation API. Ordinary intent and each exact `--allow-file` are explicitly internal. `--private-intent`, exact `--allow-private-file`, and project `--include-private` are private-local grants. Restricted/unclassified intent is denied. No tool exposes this API. |
| UTF-8 files | Owner labels are materialized only at new-task creation. No missing legacy file label defaults to internal on read/resume. Inventory, exact scope and existing physical alias checks precede the reader. Labels apply to the whole path/dataset; changes to file contents require continuing owner responsibility. |
| Memory and provenance | Owner add/remember attests the whole sourced record. New restricted or missing-label records are denied before DB/FTS writes. Retrieval verifies project/class, inventory, receipt expiry and whole-record digest, including provenance. Reindex copies only currently admitted records. |
| Persona | Owner save/initialize attests the immutable version as internal. Existing versions are not silently admitted by migration/initialize; owner review by version ID/hash is required. Persona remains untrusted user-context data. |
| Tool output | Closed descriptor, actual source scope, verification and task lineage; maximum source classification is inherited. No permission from output fields. |
| Model steps/revisions/answers | Known-credential/JSON/schema checks and admitted task lineage precede persistence. Registry resolution, immutable revisions, effect approvals and dispatch remain separate. Generated text cannot attest itself or enable a connector. |
| Saved legacy task/results | No migration receipts. Owner reviews IDs/digests. The task receipt binds intent, project, original scope, initial plan, revisions, action requests/results and final result. Counter/lifecycle changes do not grant data authority. |

`admit()` is a known-format rejection helper, **not** an authorizer or a proof that arbitrary
text is secret-free. The production orchestration/registry/worker paths enforce admission
receipts and inventory. Low-level trusted Python APIs and synthetic providers are not
remotely exposed security principals.

| Sink | Enforcement |
| --- | --- |
| SQLite/journal | New owner inputs checked before source writes. Validated task derivations refresh their content receipt transactionally; missing/expired receipts cannot bootstrap themselves. Metadata-only recovery/stop/audit remain possible. Owner reconciliation requires a current reviewed task and scoped inventory; it never bootstraps admission. |
| Worker IPC | Task and exact scope/registry binding checked before temporary IPC files/Popen; repeated in worker. Minimal environment preserved. Inventory/source labels and known credentials checked on returned data. |
| Ollama | Admitted task, persona and saved observations before messages/call; worker repeats task check. Numeric loopback only, no proxy, redirect, DNS hostname/cloud fallback. Selected model stays qwen3.5:9b. |
| CLI diagnostics | Closed error codes, withheld unreviewed/private payloads, private-task action/approval IDs and digests only; private memory content withheld. Event views expose lifecycle metadata only. Scope/evidence diagnostics deny unreviewed data. |
| Approval previews | Explicit owner request for an admitted task and its preview sink; full private content is written only to the existing protected ACL/TTL cache. No stdout content, no effect approval implied. |

Private task purpose is exactly `owner-task`; explicit grants name local `journal`, `worker`,
`ollama`, `preview` sinks. CLI private flags grant those four, not diagnostics or egress.
Owner API can narrow `local_sinks`; missing journal permission refuses task creation,
other missing permissions refuse the corresponding sink. Private create approvals remain
reviewable through metadata IDs and the protected preview. No inference from model text.

## Inventory and disabled vault

`sensitive_inventory` stores only ID, kind, project, locator/collision key, classification,
fixed owner identity/provenance, reviewed timestamp and expiry. Paths are exact relative
workspace files (no recursive directory crawling); other locators are task/memory/persona/
preview IDs. No secret values, source excerpts, OS credentials or automatic imports are stored
in inventory. Locators themselves are owner-attested metadata; do not put secrets in names.
Persisted file denial keys use the same conservative NFC/casefold function on both platforms,
so relocating a database cannot silently lose a mark. This can block distinct Linux/Unicode
spellings too; it never resolves a path or creates a weaker file grant.

Every new mark blocks even if labelled internal until a separate owner review. Restricted
and unclassified marks always block; reviewing a restricted mark as restricted does not
release it. Changing the metadata label is an explicit owner attestation, **not** a new tool
scope. A reviewed private mark cannot pass an internal grant. Expired marks block rather than
disappear. New receipts expire after 30 days; manual reviews require future expiry (max 366
days). Normal derivations retain the original task expiry, not an indefinite sliding renewal.
Revocation is an explicit restricted inventory mark/review, not deletion of source data.

`vault.py` defines a minimal credential-use request (inventory ID, connector, project, origin,
purpose). `DisabledWindowsCredentialManager` always denies. It has no get/list/import/put
credential API, invokes no Windows credential function, and returns no secret-bearing handle
or bytes. A real backend and its API/evidence must be reviewed separately before activation.
This is a candidate Windows Credential Manager boundary, not a working vault integration.

## Legacy review and migration

SQLite v4 adds exactly three tables: `data_admissions`, `sensitive_inventory`, `data_reviews`.
The migration does not change task/source/scope/action/approval/result/preview rows and does
not create admission receipts. v1/v2/v3 upgrades create an integrity-checked online backup
before a single transactional migration. Negative, future and unversioned nonempty schemas
are refused; errors roll back the schema transaction. Reopening v4 does not migrate or make
another upgrade backup. The executor lock serializes upgrades. Backups are private runtime
state and can contain old sensitive data; they are not encrypted by this application.

`data-audit --project PROJECT` returns bounded IDs, labels, review digests and status only.
It hashes stored source documents locally but does not display bodies, intent, paths,
statements, provenance text or preview content. Identity versions have the explicit
`identity` namespace. v3 preview rows have no project binding: only the explicitly requested
`legacy-previews` namespace lists global registered preview IDs/expiry; a project audit does
not list another project's previews. Unregistered cache files are not scanned.

`data-review` binds a single existing object ID/project/digest to its **unchanged** label.
It records an append-only metadata review plus current receipt. Stale hashes or lower labels
fail. The owner must inspect original content independently before attesting; the audit is
not a content review. Missing/ambiguous file labels still block even after a task review:
create a new explicitly scoped task, never normalize or rewrite the old scope. Existing
effects/approvals are retained; review neither consumes, recreates, deletes nor reuses an
approval. Verified actions remain skipped, uncertain effects remain reconciliation-bound.
Legacy preview IDs can be marked/reviewed as inventory metadata, but are never loaded or
recreated by the audit/review path. Existing ACL/TTL cleanup semantics are unchanged.

Restore procedure: stop execution and close all connections; retain the failed/new root;
restore the verified pre-upgrade backup and matching code into a separate root; inspect
`PRAGMA integrity_check` and `user_version` before opening the app. Restore identity separately.
Never decrement `user_version` or remove tables in production. Older code ignores the new
admission policy, so rollback is not authorization to resume private tasks; it needs owner
review. No deployment, production migration or personal-data review was performed here.

## Connector gates and evidence limits

`spec/connector-gates.json` lists browser/document/spreadsheet, Telegram/email/cloud,
desktop/voice/calendar and links each to actual M2–M4 task IDs. Every contract requires source
classification; origin/recipient/target scope; credential isolation; injection resistance;
outbound consent; one-use approval; and reconciliation after uncertain effects. CI validates
coverage and prevents M1 contracts from claiming enablement or real adapter evidence.
Fixtures exercise disabled/default-deny and closed-registry behaviour under forged claims.
They do **not** test an actual browser, parser, account, microphone or external sender.

Before enabling a real connector, a separate reviewed change must replace its disabled
contract with actual adapter tests/evidence for every required check and owner enablement.
No synthetic fixture or mere boolean assertion is accepted as integration evidence.

Regression retains 8/32 KiB full-source-or-receipt partial outcomes, exactly-once creates,
immutable revisions, approval retention, safe recover, backup and preview ACL/TTL. Windows
alias code and Linux ADR-021/Landlock are unchanged. Fresh counts, commit/CI and live-host
availability are recorded separately in `evidence/m1-trust-validation.json`.
That file is a snapshot at its named implementation commit. [PR #8](https://github.com/branch-danya-dev/assistant/pull/8)
records the final HEAD/CI, including the subsequent portable inventory-key regression and
a repeated live-host availability check; earlier test counts are not final-HEAD evidence.

## Risk register

| ID | Remaining risk / disposition |
| --- | --- |
| R-M1-OWNER-CLASSIFICATION | Opaque/encoded secrets wrongly attested internal/private-local can pass. Inventory completeness and accurate labels belong to owner. Tests prove denial **when marked**, not universal discovery. Original REQ-019 stays open. |
| R-M1-LEGACY | Old contents remain in DB/pages/backups and existing previews. No automatic erasure or bulk content disclosure. Unreviewed sources fail closed; missing labels require new tasks. |
| R-M1-METADATA | Locators/IDs and digests are sensitive metadata; low-entropy content hashes can be guessed. Protect DB/backups and do not publish runtime inventory/review reports. |
| R-M1-HOST | Same-account code/DB modification, untrusted dependencies and arbitrary external Git clients are outside this app boundary. No repository-wide DLP claim. |
| R-M1-VAULT | Real Credential Manager backend disabled and unverified; no credential-consuming M1 tool. |
| R-M1-CONNECTORS | Only synthetic disabled contracts exist. Actual connector gates remain mandatory before enablement. |
| R-M1-ALIASES | Real 8.3 fixture availability and real Windows case-sensitive-directory certification remain explicit limits. No universal filesystem claim; unsupported cases fail closed. |
| R-M1-LIVE | Historical Qwen successes are not new evidence. Fresh selected-model availability/inference must be recorded for this runtime before eventual acceptance. |
| R-M1-DECISION | ADR-025 decisions still pending; original P0 acceptance/statuses remain unchanged. |

Integration only after separate owner instructions: #4 → #5 → #6 → #7 → this stacked PR,
with fresh CI/review after separately authorized integration/retargeting. No merge is implied.

## PR #8 review remediation (ADR-027 / TASK-050)

Review provenance: [5722142390](https://github.com/branch-danya-dev/assistant/pull/8#pullrequestreview-5722142390),
reviewed parent `8cc373cb46b283b58b72de3837ba33d6128e69d2`. The same branch and stacked base are retained.

**Reconciliation:** the owner must supply the exact project and current task digest, plus an
observed outcome and bounded evidence reference. Within one SQLite write transaction, the
existing admission/scope/inventory/saved-memory chain is validated before any mutation; old
admission metadata are appended to review history, result and owner event are saved, task stays
non-replayable, and the new digest receipt retains its old expiry. A failure rolls everything
back. The event is an owner assertion, not a tool-verifier claim. Repeated reconciliation or
replacement evidence is refused. Stop/cancel controls, attempts, budgets, effect approvals,
original scope and plan revisions remain unchanged. Resume also rejects any reconciled action
even if a later state transition changed the task's block reason. Missing, expired, marked or
restricted tasks require separate explicit owner review/renewal; reconciliation has no bypass.

**Memory index:** mark/revocation immediately removes the exact project/ID entry. A metadata
inventory review may restore only a still-current, exact prior content receipt. A legacy review
or renewal updates admission and that one eligible FTS entry atomically. Canonical ID/project,
class and statement columns must match the document; digest, inventory, retention and removal
are rechecked. A denied entry is suppressed. Full rebuild uses the same predicate. No bulk
re-admission or automatic source rewriting occurs. Private project scope is unchanged.

**Lifetime:** 30 days is authorization lifetime, not deletion/retention. Explicit owner-only
`data-renew` binds ID + project + unchanged current/previous digest + classification + future
expiry (max 366 days and later than previous expiry). Previous and replacement receipt metadata
are appended to v4 `data_reviews`. It cannot renew changed/missing receipts, release revoked or
expired inventory, extend canonical retention or resurrect removed records. Task dependencies
and existing sink grants are rechecked. `data-review` remains the independent legacy/content
review API; it also preserves prior receipt metadata. Neither operation approves an effect.

`show-audit --project` provides bounded payload-free historical diagnostics after expiry or
revocation; `show` uses this fallback when admission is unavailable/private. Current state,
IDs, action/approval status, digests, event headers and review metadata remain inspectable;
source content, paths and evidence-reference text remain withheld. Archive/backup content has
no permanent projection exemption. See [commands and restrictions](runbook.md#renewal-and-historical-audit-pr-8-remediation--adr-027).

SQLite stays v4; no migration or previous grant/journal rewrite. Existing matching-backup/code
rollback instructions apply. The correction does not repair previously stale reconciled
receipts automatically: inspect the original evidence and perform explicit ID/digest review.

| Regression evidence | Scope |
| --- | --- |
| `tests/test_trust_lifecycle.py` | Atomic receipts/index, both reconciliation outcomes, denial cases, renewal, payload-free history, stop/cancel and cross-project/private scope |
| `tests/test_m1_create.py` | Real child crash after actual synthetic create; before-effect uncertainty; receipt visibility and no replay |
| Existing full suite | Aliases, partial 8/32 KiB, approval consumption, revisions, migration/rollback, preview ACL/TTL, disabled connectors |

Fresh validation/provenance is recorded in `evidence/m1-trust-remediation.json`; the final HEAD
and CI are also reported in PR #8. No historical Qwen success is counted as a new pass.

Additional residual **R-M1-RENEWAL**: owner review remains manual; incomplete inventory or wrong
classification is not fixed by renewal. Wall-clock expiration suppresses retrieval immediately,
but stale derived FTS bytes need rebuild and physical/backup erasure remains deferred. Historical
metadata is sensitive and may be truncated; full canonical evidence remains retained locally.
All existing risk-register entries and the three pending ADR-025 decisions remain open.

## Mixed-admission search follow-up (review 5722293592)

Reviewed parent: `46890be03a4fe9bb57d51e559d80c1b105838809`. The regression reproduced
`source_review_required` for both creation orders of an expired and a still-admitted match,
including an expired newest candidate with `limit=1`.

Search now joins current memory admissions and filters project, matching classification,
removal, canonical retention, admission expiry and active matching inventory **before**
sorting and candidate limits. Missing/expired receipts cannot occupy result slots. A separate
full check validates canonical ID/columns/schema, nonempty source provenance, the whole-record
digest, receipt owner/provenance/class and current inventory for each candidate. Known source
denials omit that record and continue; they do not authorize, renew or return its payload.
The same checks protect `superseded_by` IDs, even when a successor does not match the query.

The query retains literal Unicode word escaping (24 words maximum), no global BM25 statistics,
and descending recorded time; ID ascending breaks ties deterministically. It returns up to
the requested 1–20 **valid** results. Full checks are limited to **256 unique records per search**,
shared with successor checks, with one candidate lookahead. Metadata-only filtering does not
consume this budget. If more full checks are needed, `memory_search_budget_exhausted` aborts
with no partial payload; orchestration reports a paused task rather than an empty successful
search. This explicit availability limit avoids an unbounded validation walk through damaged
records. Ordinary SQL metadata filtering/sorting still scales with the scoped dataset; worker
time and output limits remain enforced. Use a narrower query or explicit owner reindex/review
after diagnosing the cause; no scheduled cleanup or silent reauthorization is required.

Only the enumerated source-denial codes in `memory.RECORD_DENIALS` are skippable, including
schema-invalid records and recognizable credential content. SQLite/schema-table failures,
malformed JSON, I/O and unexpected/internal errors abort the operation. Public CLI/worker
diagnostics retain their closed error codes. This intentionally distinguishes an unavailable
source from a failed storage/policy subsystem; a broad `except AgentError: continue` is not used.

A SQLite transaction serializes selection/checks with owner mutations and removes encountered
digest/provenance-denied FTS entries atomically. Failure rolls back pruning; an existing caller
transaction is neither committed nor replaced. Add/review/renew/rebuild use the same full-check
helper; revoked, expired-retention and removed data are not indexed. Metadata-filtered stale
entries after elapsed expiry may remain physically until explicit rebuild but cannot authorize
retrieval. Canonical records, receipt/history lifetime and effect permissions remain unchanged.
SQLite remains v4 without a new migration. No protection against malicious same-account
database/code edits or physical erasure is claimed.

`tests/test_memory_admission_search.py` adds 16 tests covering both orders, missing/expired
mixtures, all denials, 40 leading invalid candidates, explicit budget/rollback, successor
checks, late mutation, owner lifecycle, reload/rebuild, CLI privacy and a real child-worker
workflow with captured input/output and no replay. The former lone-source denial assertions
now require an empty result, retaining their nondisclosure requirement. Installed-wheel
validation outside the checkout also exercises mixed expiry, 12 tampered leading candidates,
renewal and rebuild. Final SHA/Windows+Ubuntu CI are recorded in PR #8; evidence snapshots
name their own tested revision rather than claiming a later docs-only revision was tested.

Residual **R-M1-SEARCH-BUDGET**: sufficiently many digest-invalid matches or history links can
reach the explicit 256-check limit; this is a visible resource stop, not a successful truncated
result. The local database lock may also cause a closed storage error under contention. This
bounded behaviour does not alter ADR-025 or close TASK-050/044/026/M1 acceptance gates.
