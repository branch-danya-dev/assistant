# Project status — first implementation, 2026-10-30

M0 is complete; M1 is in_progress after independent review. REQ-017/019 remain specified P0/M1. Runtime includes migrations, immutable plan revisions,
memory/persona, approved create-only files, bounded workers, crash recovery, Ollama and owner CLI. See `m1-completion.md` and
`runbook.md` for checks and supported operation boundaries.

Selected qwen3.5:9b completed a synthetic live Windows task: read a scoped file, search project
memory, produce an evidence-linked result and preserve state after reopening. With explicit
owner consent, model files were copied and SHA-256-verified at G:\Assistant\models\ollama;
User variables and model files on disk were verified; the running process environment and loaded model memory were not independently verified. Originals retained; no comparison
or model download performed.

TASK-043 retains scoped acceptance. TASK-026 and dependency gates TASK-009/010/041 are reopened;
TASK-044 retains unchanged P0 security acceptance. See m1-review-fixes.md for current evidence. PR #4 and the
stacked PR remain unmerged pending the owner's integration decision; main is unchanged.
Windows is primary. Linux is owner-approved trusted environment with flat output names,
Landlock and no unsafe fallback; full nested create paths are supported only on Windows.
Generic secret detection/vault integration is not claimed. M2/M3/M4 tools remain deferred.
No real outbound message, purchase, installation or destructive executor is active.

Canonical statuses/evidence in spec/ distinguish these gaps from implemented behavior.
Architecture Baseline v1.0 remains the accepted design contract.

The next stacked security change removes TASK-044's dependency deadlock and adds explicit
TASK-026 acceptance gating. Current implementation/evidence and precise unmet conditions are
in [m1-security-boundaries.md](m1-security-boundaries.md). Completion order is TASK-044 →
TASK-026 → TASK-041 → TASK-009 → TASK-010; M1 and REQ-017/019 stay open.
