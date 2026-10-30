# Project status — first implementation, 2026-10-30

M0 complete; M1 partial. A working local read-only vertical slice exists: migrations, journal,
memory/persona, trusted policy, crash recovery, Ollama and owner CLI. See `m1-evidence.md` and
`runbook.md` for checks and supported operation boundaries.

Selected qwen3.5:9b completed a synthetic live Windows task: read a scoped file, search project
memory, produce an evidence-linked result and preserve state after reopening. With explicit
owner consent, model files were copied and SHA-256-verified at G:\Assistant\models\ollama;
User variables and actual running model paths were verified. Originals retained; no comparison
or model download performed.

Remaining M1 work: audited revision of running plans (TASK-009), interface gate closure after
orchestration acceptance (TASK-010), safe create-only workspace writes (TASK-043) for REQ-025.
Generic secret detection/vault integration is not claimed. M2/M3/M4 tools remain deferred.
No real outbound message, purchase, installation or destructive executor is active.

Canonical statuses/evidence in spec/ distinguish these gaps from implemented behavior.
Architecture Baseline v1.0 remains the accepted design contract.
