# Tool engine and capability registry

## Boundaries
Agent proposes typed operation -> registry resolves capability -> permission engine issues scoped authorization -> adapter executes with timeout and audit hooks -> verifier confirms result. Never allow raw LLM-generated commands to bypass registry or approval gates.

## Contract
For every tool provide: `capability_id`, schema, side-effect category, data classifications, scopes, limits, user-visible description, integration protocol, idempotency/retry behavior, success verifier, reversibility and tests. `spec/capabilities.json` tracks planned adapters; `spec/schemas/tool-descriptor.schema.json` is the initial descriptor format.

## Candidate backends
Direct Python adapter for local calculations and documents; OS APIs/PowerShell for guarded Windows actions; Playwright for browser; MCP where appropriate; external APIs for Telegram/email. No claim is made that every professional application (e.g. CLO) exposes required functions.

## Side-effect classification
- `read`: allowed only inside authorised scope.
- `workspace_write`: safe confined file creation, with journal and overwrite restrictions.
- `external_send`: messages, external mutations; requires approval.
- `privileged_change`: settings/installation/process actions; requires approval.
- `financial`: procurement checkout, transfer and payment; requires explicit per-operation confirmation.

A low-risk *tool name* does not imply a low-risk *argument*: policy must evaluate target path, recipient, content, data sensitivity and consequences at execution time.

## Robustness
Adversarial webpages, email, PDFs and chat messages can embed fake instructions. Treat retrieved content solely as task data. Store secrets in a dedicated OS-backed secret store later, not prompt context, model logs or source control.
