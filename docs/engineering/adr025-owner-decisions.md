# ADR-025 owner decisions — pending

Implementation of bounded option B controls is authorized. Approval of the acceptance
agreement is **not recorded**. Machine record: `spec/owner-decisions-adr025.json`; answers,
owner, date and approval reference are null. ADR-025 remains provisional.

The owner can answer these three items explicitly in the next chat:

1. **Bounded acceptance:** approve option B for the enumerated M1 sources/sinks, with owner
   responsibility for classification/inventory and no claim of discovering all unknown secrets?
2. **Data and vault:** approve default-deny, explicit internal/private-local attestation,
   ID/hash legacy review without changing old authority, and Windows Credential Manager as a
   future backend whose M1 adapter remains disabled?
3. **Future gates:** approve mandatory real connector checks at their M2–M4 stages, and require
   fresh selected-Qwen plus Windows/Ubuntu evidence before eventual M1 closure?

Record explicit yes/no/qualified answers referencing ADR-025 and these numbered items in a
separate reviewed change, including date and owner decision reference. Qualified answers
require reconciliation with the proposed scope; they are not silently treated as full approval.
Only then consider ADR-025 accepted and propose explicit requirement acceptance/traceability
changes. P0 priority, original decision history and outstanding evidence remain visible.
Implementation success does not itself close TASK-044/026 or M1. No answer authorizes merge,
retargeting, deployment, real credential use or external connector activation.
