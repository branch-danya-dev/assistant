# Independent release audit remediation — PR #8

Parent: 6e5bef8de4bf4207e703b91fdbdbf2cf10066b2c, tree
4c16767e83ad81d3550c3af81c0a69e714a9ea25. Review 5723022076.

The three supplied reproducers were rerun on the original installed wheel in fresh
synthetic roots. Confirmed: private approve stdout exposes a path even after task
admission expiry; 101 inventory entries report truncated=false; the original local
installed_acceptance.py reports an Ollama error but exits zero. Original wrapper SHA256:
2f7768209376b8401828d6ffa80f99e1d7a50438a8f412d25157917e163f04de.
All 23 original release-manifest and 31 independent-audit-manifest hashes were checked,
including corresponding ZIP payloads and CRC. The old packages remain historical evidence.

## Corrections

Owner approval now rechecks Trust.require_task inside BEGIN IMMEDIATE, then binds both
directions of approval/action/task, saved plan request, resource, effect and recomputed
scope-dependent digest. Missing/expired/foreign/revoked or changed admission/scope/request
fails before writes; later failures roll back approval, task and events together. Ordinary
CLI returns only approval_id, status, arguments_digest and safe_status. Protected preview
and dispatch verification remain separate. Model approval is still unregistered; approved
effects remain exact and consumed once. This is no admission renewal or same-account DB
tamper-proofing claim.

Audit has 101-row lookahead for every database collection and full persona-list overflow
detection. Each collection has a 100-item limit; items plus inventory share total_limit=300.
Order is deterministic (collection order, IDs; persona numeric versions). Any omitted row
sets truncated=true. No pagination or content exposure; a truncated audit is not complete.
Persona filename enumeration and SQL scans still scale with the local dataset.

tools/installed_acceptance.py is the maintained replacement for the external release
wrapper, not a change to tools/verify_host.py (whose exit handling was already correct).
Separate smoke/workflow child processes each require exit 0 AND explicit passed=true,
PASSED status and boolean checks. Exceptions, timeout, malformed JSON, blocked/partial
workflow and connection refusal fail with nonzero and machine-readable FAILED.
Doctor is diagnostic, never a live gate. Tests use a numeric-loopback HTTP stub and run
the actual model adapter, workers, journal and verifier without external services.

The revised [TASK-011 contract](M2-TASK-011-spec.md) defines fixed_cost_total once per
batch, variable_cost_per_unit times quantity, explicit units/currency, Decimal exact
calculation and independent verification, zero/negative/nonfinite/budget behavior and
distinct gross-margin/markup denominators. An owner-authorized experimental draft is
allowed after this remediation's checks, with explicit opt-in and no M1 closure.

## Reproduce

Run full unittest discovery, tools/validate_specs.py, Ruff (including the new harness),
wheel build and tools/verify_package.py. The platform CI matrix runs the same suite.
New tests: test_release_remediation.py and test_release_harness.py. Existing approval,
forged-model, recovery/reconciliation, FTS, SQLite v4 migrations, aliases, ACL and Landlock
tests remain required. Platform-specific skips must be reported.

For an optional live check, install the wheel in a separate environment, copy the tracked
tools/installed_acceptance.py outside checkout and execute:

```
python installed_acceptance.py --root ABSOLUTE_FRESH_SYNTHETIC_ROOT --output live.json
```

Require process exit 0 AND parsed JSON passed=true/status=PASSED. Local qwen3.5:9b must
already be running; no pull/configuration change is performed. It tests two smoke model
calls and two read/search workflow calls. It does not certify model files, hardware,
live mutation/revision, production data or full M1 acceptance.

ADR-025 is provisional, OD-1/2/3 unanswered, REQ-017/019 specified P0/M1, M1 and TASK-009
in_progress. All owner-classification, incomplete inventory, opaque-secret, same-account,
backup/erasure and unsupported-filesystem limitations remain. No merge, retarget, rebase,
deployment, production migration or credential/configuration access is authorized here.
