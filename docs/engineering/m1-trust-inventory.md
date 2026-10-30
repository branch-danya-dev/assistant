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
| SQLite/journal | New owner inputs checked before source writes. Validated task derivations refresh their content receipt transactionally; missing/expired receipts cannot bootstrap themselves. Metadata-only recovery/stop/reconciliation remain possible without admitting legacy content to model/tools. |
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
