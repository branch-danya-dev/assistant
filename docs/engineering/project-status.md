# Project status — first implementation, 2026-10-30

M0 and M1 acceptance complete on the stacked implementation branch. Runtime includes migrations, immutable plan revisions,
memory/persona, approved create-only files, bounded workers, crash recovery, Ollama and owner CLI. See `m1-completion.md` and
`runbook.md` for checks and supported operation boundaries.

Selected qwen3.5:9b completed a synthetic live Windows task: read a scoped file, search project
memory, produce an evidence-linked result and preserve state after reopening. With explicit
owner consent, model files were copied and SHA-256-verified at G:\Assistant\models\ollama;
User variables and actual running model paths were verified. Originals retained; no comparison
or model download performed.

TASK-009/010/043 passed acceptance; evidence is recorded in m1-completion.md. PR #4 and the
stacked PR remain unmerged pending the owner's integration decision; main is unchanged.
Windows is primary. Linux is owner-approved trusted environment with flat output names,
Landlock and no unsafe fallback; full nested create paths are supported only on Windows.
Generic secret detection/vault integration is not claimed. M2/M3/M4 tools remain deferred.
No real outbound message, purchase, installation or destructive executor is active.

Canonical statuses/evidence in spec/ distinguish these gaps from implemented behavior.
Architecture Baseline v1.0 remains the accepted design contract.
