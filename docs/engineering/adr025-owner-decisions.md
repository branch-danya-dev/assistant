# ADR-025 owner decisions — accepted option B

**OD-1=YES, OD-2=YES, OD-3=YES; recorded 2026-10-31.**
Machine record: `spec/owner-decisions-adr025.json`. Acceptance-policy approval is recorded;
it is not evidence of complete security, M1 completion, or integration/deployment approval.

## Source and date

The owner confirmed all three items in the conversation
[Создание ИИ ассистента](chatgpt-conversation://6ae2f340-af5c-83ed-8443-188cbf41cabd).
`read_thread` returned the actual question message
`36839057-740d-41f8-a338-c6eb608d2fba`, the affirmative owner-answer message
`5226bda2-bfcc-44f2-8144-fb9fc02c4e74`, and the subsequent three-item enumeration
`cf0c785b-5ac5-4ccb-9d10-78b80b6a8dff`. The question explicitly covered all three
ADR-025 items; the answer affirmed proceeding. The current owner instruction explicitly
reaffirms that scope. The assistant enumeration corroborates scope but is not owner authority.
No private conversation transcript is copied into Git.

The answer turn's returned `startedAt=1793462402.326` is
**2026-10-31 16:00:02.326 UTC / 19:00:02.326 Europe/Moscow**. This supports the decision
date; `recorded_at` is the date of this record. A chat reference may require account access
and is not a public GitHub review. No independently verified account identifier was supplied:
`owner_identity` remains null. No GitHub approval comment exists or is invented.

## Approved boundaries

1. **OD-1:** bounded M1 acceptance only for the enumerated sources/sinks in
   `spec/m1-data-contract.json`. The owner is responsible for classification and inventory
   completeness. Unknown/encoded/misclassified secrets are not universally discoverable.
2. **OD-2:** default-deny; explicit internal/private-local grants; legacy ID **and hash**
   review without authority expansion, automatic relabeling or effect replay. Windows
   Credential Manager is only a future vault candidate; the M1 adapter stays disabled.
3. **OD-3:** mandatory, separate real-adapter functional/security gates at M2-M4; fresh
   Windows/Ubuntu and selected local `qwen3.5:9b` evidence before M1 closure. Separate explicit
   owner consent for each merge/deploy remains required.

The [acceptance revision and evidence matrix](adr025-acceptance-traceability.md) preserves
original REQ-017/019 wording, P0, residual risks and dependency gates. Do not ask the owner
to approve these same three decisions again. Nothing here authorizes merge, rebase,
retarget, deployment, reading production databases/secrets, or enabling vault/connectors.
