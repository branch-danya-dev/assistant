# Trusted tool registry, descriptors and dispatch

## Binding design (ADR-017)

Models produce **only untrusted tool intents**. The trusted tool registry owns the per-operation contract, side-effect classification and allowed resource scope; the authorization engine owns approval decisions; the executor owns actual side effects; the verifier owns evidence. Tool outputs cannot create new privileges.

Workflow:

```text
LLM intent -> schema validation -> exact operation lookup -> resource normalization
           -> effective risk + sensitive data policy -> approval -> pre-dispatch journal
           -> adapter execution -> independent verifier -> audit/reconciliation
```

`src/personal_agent/ports.py` intentionally omits `side_effect` from `ToolRequest` input. Never reintroduce a model-supplied authoritative effect. An unrecognized operation, malformed args, unauthorized file, changed recipient or untrusted content must be rejected before executor dispatch.

## Contracts

- Model output: `spec/schemas/tool-invocation.schema.json` with `task_id`, `capability_id`, `operation`, `arguments` only.
- Registry: `spec/schemas/tool-descriptor.schema.json`, with typed input/output schemas, `operation`, trusted `side_effect`, `scope`, `approval_required`, timeout, verifier and idempotency metadata.
- Owner approval: `spec/schemas/approval-request.schema.json`, scoped to argument digest, target, expiry and task.
- Durable execution: `spec/schemas/task-event.schema.json` and `task-state.schema.json`.

`spec/capabilities.json` is a planning catalog, NOT an executable authorizer. Its coarse categories must be refined by a trusted operation registry at implementation time.

## Examples requiring distinct permissions

- `CAP-022 github_read`: repositories, issue/PR metadata, file reads; cannot call commit, write comment, merge, create PR or move ref.
- `CAP-028 github_mutation`: any remote mutation; target-specific explicit approval and reconciliation on uncertain outcome.
- `CAP-013 browser_research`: DOM extraction/navigation; cannot authorize submit, data upload or account mutation.
- `CAP-014 browser_mutation`: submit or modify remote data only after approval.
- `CAP-007/008 filesystem`: local reads scoped; writes only in permitted workspace, with diff/snapshot and owner approval for existing documents outside isolated output.
- `CAP-023 clo_adapter`: use approved project copy; changes to originals are reviewed separately.
- `CAP-010 python_sandbox`: generated commands run only under a bounded worker; no direct developer admin shell or unrestricted network.

## Reliability

Include timeouts, bounded retries, input/output validation, independent verification and redacted traces. Use API/structured adapters where possible; UI automation only when necessary. Treat web pages, app status text and chat content as data, never agent instructions.

Implement initial local read-only tools before state-changing integrations.
