# M1 security boundaries and remaining acceptance

M1 remains **in_progress**. REQ-017 and REQ-019 remain **specified, P0, M1**,
with their original acceptance unchanged. This is implemented defence and executable
negative evidence, not certification of arbitrary secret detection or future connectors.

Latest implementation: [ADR-026 / TASK-049 inventory and admission](m1-trust-inventory.md)
adds SQLite v4 receipts, metadata inventory and manual legacy review. The v3 details below
describe the earlier checkpoint; they do not override the new fail-closed legacy policy.

PR #6 review follow-up: [file alias remediation and compatibility](m1-file-aliases.md)
enforces fail-closed Windows scope/long-name checks, hardlink rejection and legacy resume
preflight. [ADR-025 proposed acceptance agreement](m1-trust-boundary-proposal.md) is provisional,
not an owner-approved requirement change. The evidence below describes the original PR #6;
new cycle evidence is recorded separately in `evidence/m1-alias-validation.json`.

Starting point checked against GitHub: PR #5 at `62df23f2e49c6f90134d6d7ad46c7fc284d77696`,
base `feat/m0-m1-local-agent` at `42a9f31dd1556a1714d64d86ee6e8f630b027d2f`.
[Independent review](https://github.com/branch-danya-dev/assistant/pull/5#pullrequestreview-5718253568)
identified the semantic dependency deadlock. All existing commits are retained.
This branch is based on #5, not main. No deployment or existing-PR mutation is performed.

## Acceptance dependency fix

TASK-044 depends only on completed TASK-005/004. TASK-026 explicitly declares
`acceptance_depends_on: ["TASK-044"]`. The validator checks both work prerequisites
and the combined acceptance graph, including transitive cycles and premature completion.
A regression reconstructs the original deadlock without a cycle in the work-only DAG.

Independent closure order: **TASK-044 → TASK-026 → TASK-041 → TASK-009 → TASK-010**.
TASK-041/009 already have implementation evidence; neither closes before its security
dependency. All remain in_progress while the unchanged security acceptance is unmet.
Marking a status done is not evidence and cannot bypass the acceptance graph.

## Threat model

Trusted: owner CLI/API inputs defining scope, reviewed Python code and installed dependencies,
the closed registry, SQLite canonical state, and OS process/filesystem primitives.
Untrusted: every file body, memory statement/provenance, local tool result, and model response.
Assume the model obeys an attack completely. Tests use a deliberately persuaded synthetic
provider after actual bounded-worker file/memory retrieval; they do not measure Qwen resistance.

| Boundary | Enforced behaviour and evidence |
| --- | --- |
| Source → model intent | Source stays in user data; persona also moves out of the system message. Forged roles, tool calls, approvals and verification flags cannot become contract fields. |
| Intent → execution | Exact operation/input schema, owner file paths, immutable task/project, create binding and content-bound one-use approval are rechecked. Allowed create_text still stops at owner approval; UNC export and cross-project search arguments fail. |
| Windows pathname → classified object | Scope aliases/duplicates and conflicting private grants fail closed. Bounded metadata preflight at creation/resume and worker checks require exact long names, single-link files and known case-insensitive directories. No grant/approval is rebound; see m1-file-aliases.md for Unicode, 8.3 and platform limits. |
| Tool result → IPC/journal/model | Output schema and independent observation; classification and credential admission check before worker return, parent persistence and final projection, including saved legacy results. No content truncation to bypass a denial. |
| Memory → retrieval | Project/class SQL filtering precedes ranking; returned records are rechecked. Restricted is never an M1 retrieval grant. Legacy recognizable credentials are rejected before return. |
| Model → saved plan/revision/result | Recursive credential admission before saving; model-provided verification fields and invented evidence refs fail. A model summary remains unverified prose, never proof that a new action happened. |
| Worker process | Minimal task identifiers instead of full owner intent. Environment contains only Windows OS anchors and fixed Python settings. No inherited tokens, proxy, PATH, OLLAMA_HOST or owner PYTHONSTARTUP. |
| Errors/diagnostics | AgentError accepts only reviewed static codes. Wrapped source/OS/parser exception chains are suppressed in rendered tracebacks. CLI parse errors do not echo arguments. Query/revision text is a receipt; private task summaries are withheld. |
| Egress | Numeric loopback only, rechecked immediately before HTTP connection; fixed Ollama paths; no redirects/proxies/cloud fallback. No network, registry, environment-read or shell tool is registered. |
| Future webpage/email/Telegram/browser | Synthetic adapter-admission contract always denies. Production registry has no corresponding adapter. No real connector integration is claimed tested. |

Tests: `test_injection_boundary.py` runs seven payloads against both real file and memory
results: ignore owner instructions, system-role spoofing, fake results, fake approvals,
cross-project retrieval, supported writes without approval and UNC exfiltration.
`test_data_boundary.py` checks result-field forgery, generated create credentials, scoped
private/restricted/foreign canaries, nested JSON (including serialized JSON), free-text
credential patterns, legacy memory provenance, error/traceback/stdout leakage, actual child
environment, loopback recheck and registry-operation denials. Canaries are generated synthetic
values; no owner secrets or production memory are used.

## Data admission contract

`data_policy.py` provides two distinct controls:

1. **Owner classification:** whole-file `file_classes` in durable task scope; public/internal
   are local context only, private requires an exact `private_files` grant, restricted is
   denied before the worker reads it. Memory uses existing record sensitivity plus exact
   project/class scope. A source cannot relabel itself or extend scope. Existing `--allow-file`
   remains an explicit internal-file local-context grant; this does not prove its contents
   nonsecret. `--allow-private-file path` records both the private label and the explicit
   permission for local tool IPC, canonical task evidence and Ollama context. `--include-private`
   continues to grant local private-memory context. Neither permits remote submission.
2. **Recognizable credential denial:** recursive inspection of dictionaries, arrays and nested
   JSON strings rejects credential keys, private-key headers, selected token prefixes and
   labelled credential assignments. The whole input/result fails before the relevant sink.
   This is defence in depth with false positives and false negatives, not a secret classifier.

System messages contain trusted protocol/tool definitions only. Private data authorized for
local inference is supplied as user data, not system policy. Canonical evidence still stores
the complete authorized content; a privacy denial never silently replaces a retained record.
Private read summaries are withheld from `run/show` diagnostics; explicit owner memory search
with `--include-private` still intentionally returns those scoped records. Approval previews
remain an explicit private owner review artifact, with the existing ACL/TTL rules.

## Unmet P0 acceptance and decisions needed

| Risk | Unmet acceptance / evidence | Required next decision or work |
| --- | --- | --- |
| R-M1-SECRET-OPAQUE | Arbitrary unlabelled prose, an unknown/encoded credential or a wrongly labelled internal file can pass admission and enter allowed local prompts/canonical evidence. The explicit residual test admits an opaque synthetic value. Therefore literal REQ-019 “No secrets in prompts/logs/repo” is NOT established. | Owner must approve an authoritative secret inventory/vault and reviewed data-admission model, or an explicit revision of literal acceptance. No such revision or lower priority is made here. Until then do not admit real secrets; keep TASK-044/026 and M1 open. |
| R-M1-LEGACY | Existing SQLite/FTS, backups, old previews and persona may already hold unlabelled sensitive data. No secure erasure, vault migration or universal repository secret prevention is implemented. | Owner-scoped inventory/migration with backup and retention decisions; no automatic deletion or historical rewrite. |
| R-M1-INTEGRATIONS | External source adapters do not exist. Fail-closed synthetic fixtures do not certify real webpage/email/Telegram/browser boundaries. REQ-017 stays specified. | Review and test each real adapter before enabling it; preserve source/intent/policy separation. |
| R-M1-SEMANTICS | A model can misinterpret a source or write misleading prose even with valid citations. Only tool effects/evidence are verified. | Independent semantic acceptance if the product needs verified prose; do not equate completed tool execution with truthful model text. |
| R-M1-HOST | New code needs a fresh selected-Qwen host result; historical successes apply only to their own source fingerprints. | Run the synthetic host verifier only when local Ollama is available; no model download or comparison. |

Out of boundary: malicious owner/same-account native code, compromised Python/dependencies,
OS administrator, malicious loopback service or Ollama forwarding on its own, shell history,
process inspection and arbitrary external Git clients. Minimal worker environment is not a
general executable-code sandbox. Linux retains ADR-021 trusted roots, flat-create and Landlock;
Windows interrupted writes can require reconciliation. These are explicit limitations, not
silent exemptions closing the original P0 requirements.

## Compatibility and regression

SQLite stays v3. No migrations, action IDs, approvals or stored source content are rewritten.
v1→v2→v3, pending approvals, immutable revisions and evidence tests remain mandatory.
Legacy unambiguous task scopes retain their exact file grants; ambiguous scopes are blocked
before model/tool dispatch without relabelling. Optional private-file labels only add
restrictions/grants from the owner. Stricter credential admission can block an old task on
resume; it does not replay verified actions or erase data. Older binaries ignore the new
scope labels and therefore must not be used as a privacy-policy rollback without owner review.
Back up production state before any later deployment; no deployment is included here.

The existing 8/32 KiB, honest partial, exactly-once create, digest approval, no automatic replay,
needs_reconciliation, preview ACL/TTL/cleanup, root relocation and platform tests are retained.
Current SHA, test counts, CI and fresh host availability are recorded in
`evidence/m1-security-validation.json`. CI runs contracts, unit/security/integration tests,
Ruff, wheel build and actual isolated installation/execution on Windows and Ubuntu.

Integration order, only on separate owner commands: **#4 → #5 → this stacked PR**.
After integrating a lower PR, explicitly authorize the next retarget/rebase, preserve its
commits, rerun CI/review on the resulting HEAD/base, and separately decide its merge.
