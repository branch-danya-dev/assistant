# Interface boundaries

## First client
Local API + desktop client eventually. The first implementation is an owner-only CLI:
`python -m personal_agent`. Tasks, evidence, stop, recovery, memory and persona inspection are
available; see `../engineering/runbook.md`. No GUI or unauthenticated web API exists.

## Future clients
- Desktop app: conversations, tasks, tool approvals, evidence, memory editor, cost/resource dashboard.
- Telegram bot: remote task request/status, bounded uploads, approvals with strong identity verification.
- Personal Telegram account: separate, higher-risk adapter; message sending requires review.
- Voice: local STT/TTS with explicit activation/mic controls.
- Remote access: secure private overlay, multi-factor device authentication, no publicly exposed unauthenticated local API.

## UX contract
Show task state (`planned`, `running`, `waiting_approval`, `completed`, etc.), completed tool evidence, pending gates and known limitations. Distinguish drafts from published messages and planned actions from completed ones.

## API principles
Typed inputs, authz at server boundary, per-task IDs, idempotency for state changing requests, versioned transport schemas, secret redaction. No direct browser or file write endpoints exposed without central policy enforcement.
