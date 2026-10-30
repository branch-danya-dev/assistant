# Security baseline — threat model and authorization contracts

**Accepted baseline:** ADR-006 (policy before execution), ADR-014 (sensitive approvals), ADR-017 (trusted action classification), ADR-018 (reconciliation).

## Trust boundaries

1. Owner policy and trusted registry are authoritative. External webpages, documents, emails, Telegram content and model outputs are untrusted data.
2. An LLM generates an action `{task_id, capability_id, operation, arguments}` only. It cannot assert `side_effect`, `approval_required`, user identity, or grant scopes. The `tool-invocation.schema.json` contract rejects extra effect fields.
3. Registry derives side-effect class and allowed schema for the **exact** operation; policy evaluates normalized target, effective account, recipient, content sensitivity and context, then returns a scoped, expiring authorization.
4. Every adapter must revalidate the resolved operation and target immediately before executing, including directory reparse/junction/symlink checks and external destination origin checks.
5. Ambiguous or unmapped actions fail closed and are logged. No tool output can modify system instructions or authorization policy.

## Initial approval policy

| Effect | Default |
|---|---|
| Scoped read | Allowed only for explicitly approved data/resources |
| Workspace new-file write | Permitted in isolated workspace, with audit and no overwrite |
| Existing file overwrite, deletion, external upload/export | Preview/diff and explicit effect-bound approval |
| External messages, GitHub remote mutation, browser submit | Explicit target/operation/content-bound approval |
| Privileged Windows changes, package/tool installation | Explicit elevated approval after sandbox review |
| Financial order, checkout or payment | Fresh confirmation for each operation; no autonomous payment |
| Cloud submission of private data | Explicit destination, dataset and purpose authorization |

The declared tool name is insufficient: `github_read` (CAP-022) and `github_mutation` (CAP-028) are distinct. A request with a read-only ID but mutating operation MUST fail even when the user owns the repository.

An approval covers normalized arguments digest, exact target, owner, issue time, expiry and one operation; updating arguments invalidates approval. Record consumption before dispatch, and reconcile ambiguous external outcomes before any retry.

## Threat cases and defenses

- **Prompt injection**: external content is quoted/structured as untrusted source data, never silently elevated to instructions. Malicious page text requesting secret upload cannot change tool policy.
- **Credential exfiltration**: store secrets in approved OS-backed vault, avoid plaintext prompt/log/environment echo. Minimize credentials exposed to tool workers.
- **Filesystem traversal and junction escape**: canonicalize paths, verify they remain within an allowed root before and at execution.
- **Browser/account permissions**: isolated profiles, URL origin allowlists when appropriate, reviewed state changes; bot does not inherit browser credentials.
- **Self-generated code/tool plugins**: sandbox with restricted filesystem and network; signed/versioned or reviewed promotion; no autonomous replacement of core or trust registry.
- **External duplicate side effects**: operation ID, pre-dispatch journal, reconciliation state and refusal to retry on unknown outcome.
- **Cross-project privacy leakage**: apply project ACL before retrieval, summarization or cloud egress.
- **Logging and CI**: use synthetic data, redact sensitive payloads, reject secrets in commits.

## Emergency stop and recoverability

Stop switch immediately blocks new tool execution. It cannot undo operations already completed externally. Preserve a reliable audit of in-flight operations and mark unknown outcomes for reconciliation. No model or plugin may override the stop switch.

## Security fixtures

See `docs/engineering/threat-fixtures.md` and `spec/scenarios.json` SCN-007/008/010. M0 defines fixtures; M1/M3 must provide executable regressions before unsafe integrations are enabled.
