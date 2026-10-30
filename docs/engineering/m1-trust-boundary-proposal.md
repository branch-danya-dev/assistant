# ADR-025 — proposed M1 trust/data acceptance agreement

**Status: provisional; owner approval required.** Recorded 2026-10-31. No original requirement,
priority, milestone or status is changed by this proposal. M1 remains in_progress;
REQ-017 and REQ-019 remain specified, P0/M1. This is a narrow proposed interpretation and
acceptance change, not evidence that either gate has passed.

## The decision

REQ-017 says “Webpage, document and message instructions cannot escalate privileges or
override owner policy.” Only local UTF-8 file, memory, tool-result and model-intent paths
exist in M1. Synthetic denial of an absent connector establishes default-deny, not an
integration test of browser/email/Telegram parsing, permissions or credentials.

REQ-019 says “No secrets in prompts/logs/repo; unauthorized cloud egress rejected.” An
arbitrary unknown/encoded secret is indistinguishable from permitted prose without an
authoritative classification or inventory. Pattern tests cannot prove the universal statement.
An inventory/vault is necessary for known credentials but cannot discover all unknown secrets
or police arbitrary Git clients, shell history and other programs under the same user account.

| Option | Consequence |
| --- | --- |
| A. Keep literal acceptance unchanged | Current correct state: M1 stays open. More pattern tests alone cannot close the universal-secret claim; absent adapters stay unverified. |
| B. Approve bounded, explicit data/trust acceptance | Recommended. Define concrete M1 sources/sinks and owner duties below; add mandatory connector gates when each adapter exists. Implement missing inventory/admission controls and rerun evidence before closure. |
| C. Pull all future connectors and general secret discovery into M1 | Expands M1 substantially and still cannot prove arbitrary-content secrecy. Not recommended; conflicts with the staged architecture without a larger owner-approved revision. |

## Proposed option B contract (not yet implemented in full)

- **Authority:** only authenticated local owner policy and reviewed code grant scope or
  change classification. Files, persona text, memory/provenance, model-generated arguments,
  revisions and nested tool results are data. No role/approval/tool-result string raises authority.
- **Sources:** enumerate and test all current ingress: owner intent/scope, UTF-8 file bodies
  and names, memory statements/provenance, persona, model responses, saved legacy results.
  Unknown source kinds and unregistered operations remain denied. Office, browser, message
  and remote account integrations remain disabled until their own gates pass.
- **Owner classification:** the owner attests each admitted dataset as public/internal or
  explicitly private-local; restricted and unclassified sources are denied. An explicit
  `--allow-file` remains an internal attestation, never evidence that bytes are secret-free.
  Missing/ambiguous labels must not infer a lower class. Before acceptance, specify and test
  how legacy grants are reviewed; the current alias fix only blocks ambiguity, not all legacy data.
- **Secret inventory/vault:** inventory credential-bearing sources and sensitivity metadata
  without copying secret values into prompts, task DB, evidence or repo. Keep credentials in
  an owner-approved OS-backed vault; future adapters receive minimum necessary handles or
  short-lived access, not prompt-visible values. Until a reviewed vault adapter exists, M1
  has no credential-consuming tool and must deny inventory-marked sources. Inventory coverage,
  imports, revocation, legacy discovery and vault API remain **work to implement**, not a claim.
- **Sinks:** before model calls, worker IPC, journal/evidence, previews and diagnostics,
  enforce source classification and known-credential denial. Private local authorization
  must name the allowed sinks/purpose; it does not permit egress. Restricted/known credential
  data fail closed. Keep payload-free errors, minimal worker environment, private previews,
  bounded retention and no unauthorized network destination. Test repository export through
  controlled tooling with synthetic fixtures; do not promise control of unrelated Git clients.
- **Proof:** adversarial executable tests assume a fully persuaded model, use actual supported
  readers/workers, check zero unauthorized dispatch and sink persistence, and retain exact
  SHA/CI/platform/skip evidence. Known-format filtering is defence in depth with false positives
  and false negatives. Opaque misclassified contents remain an explicit owner responsibility
  and residual risk; approving this is a substantive acceptance decision, not a completed test.

The proposed bounded criterion is: *For enumerated M1 ingress and sinks, untrusted content
cannot expand owner-granted operations or data scope; restricted/inventory-marked sources
and recognizable credentials are denied before those sinks; private content reaches only
explicitly authorized local sinks; unauthorized egress is denied. Owner classification and
inventory completeness are documented assumptions, not automatic secret discovery.*

Existing implementation already enforces several parts. Missing inventory/vault/admission and
legacy coverage must be itemized and implemented before closing the proposed criterion. No
cloud/connector enablement, universal secret detector or extra feature milestone is implied.

## Future gates attached to actual adapters

| Stage / existing work | Additional acceptance before enablement |
| --- | --- |
| M2 document/spreadsheet/browser reads (TASK-012/013/014) | Test actual parsers, formulas/embedded content/links, downloads and source provenance; inject hostile instructions through real tool results; prove read scopes and no upload/submit authority. |
| M3 email, Telegram bot, cloud and browser mutations (TASK-017/019/032/033) | Review accounts/origins/recipients, vault credential handling, redirect/download boundaries and default-deny egress. Demonstrate exact one-use effect approval, recipient/content binding and reconciliation after unknown send/submit outcomes. |
| M4 desktop/personal Telegram/calendar (TASK-035/036/037) | Test actual account/UI/session boundaries, approved target and mutation classes, minimal credentials, cross-project isolation and no replay after uncertainty. |

Each gate must be linked to REQ-017/019 and its actual implementation task before enabling
that connector, with adversarial fixtures and explicit owner-reviewed evidence. Synthetic M1
stubs do not satisfy these gates. Stage assignment here is a proposal, not a changed milestone.

## Concrete owner decisions

1. Approve **option B** and the bounded criterion above, including the explicit responsibility
   for accurate classification/inventory and the exclusion of arbitrary unknown-secret discovery?
   Or retain option A and keep the literal acceptance open?
2. Approve **default-deny for unclassified/inventory-marked sources**, with `--allow-file`
   treated as an explicit internal attestation, private-local grants scoped to listed sinks,
   and manual review/new task for ambiguous legacy scopes? Choose Windows Credential Manager
   as the vault backend for a later reviewed adapter, with no credential-consuming M1 tool?
3. Approve connector-specific mandatory gates at their M2–M4 implementation stages, while
   keeping all absent adapters disabled and requiring a fresh selected-Qwen host result
   and Windows/Ubuntu evidence before any eventual M1 closure?

An approval should reference ADR-025 and the selected answers. A subsequent reviewed change
must then update the acceptance text and traceability explicitly, preserve P0 priority and
decision history, implement remaining agreed controls, and collect evidence. Until that
happens, the original acceptance and open statuses govern. No merge decision is bundled.
