# Security baseline and threat model

## Threats
Prompt injection in external content; malicious packages/tools; credential exfiltration; accidental destructive file operations; uncontrolled spend; unapproved messages/purchases; model hallucinated success; cross-project privacy leakage; duplicated side effects on retry; untrusted web automation.

## Non-negotiable policies
1. **Default deny** for sensitive paths, secret stores, external sending, financial operations, installation and privileged OS mutation.
2. **Pre-execution** approval, not retrospective consent. Approvals are bound to a specific operation, target, arguments, expiry and task.
3. **Content/data cannot change policy**: websites/documents/tool outputs have no authority to escalate permissions.
4. **Sandbox new executable artifacts**; owner review + tests before trusted tool registry installation. Avoid running generated code in a privileged main process.
5. **Audit** proposed, authorized, executed, verified and failed actions with redaction of sensitive values.
6. **Abort switch** stops issuing new operations; report any irreversibly in-flight effects.
7. **Egress policy**: no private data to cloud without an explicitly applicable owner opt-in. Local mode must block inference traffic to external providers.
8. **Least privilege** service accounts, file scopes and browser session profiles; never share OS admin token with model.

## Initial permission matrix
`read` scoped and logged; `workspace_write` scoped with overwrite policy; `external_send` confirm; `privileged_change` confirm; `financial` explicit operation-specific confirm. Any action may be elevated based on context/sensitivity.

## Secure development
No production secrets, customer data, emails or local memory in repository/CI fixtures. Test prompt injection and unsafe tool requests systematically. Do not assume containerization is a complete security boundary on Windows; review chosen sandbox implementation separately.

## Design review gates
Any new network connector, auto-execution, memory export, cloud routing, runtime plugin loading, elevated Windows integration or self-modification requires a documented threat assessment and decision entry.
