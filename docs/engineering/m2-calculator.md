# TASK-011 / CAP-009 — experimental numerical slice

This draft starts strictly at corrected PR #8 commit
ee7dbdd871306451a1ea9b44715ac7f3689b192e after its Windows/Ubuntu CI succeeded
([41208680692](https://github.com/branch-danya-dev/assistant/actions/runs/41208680692)).
The owner's 2026-10-31 instruction explicitly permits isolated implementation before
TASK-009/M1 acceptance closes. It does not permit release/main integration or acceptance
shortcuts. TASK-011 and CAP-009 are in_progress; REQ-026/039 and SCN-002 stay specified.
ADR-025 provisional, OD-1/2/3 unanswered, REQ-017/019 P0/M1 unchanged. No M2/MVP completion.

## Implemented contract

[Normative numeric specification](M2-TASK-011-spec.md) and four closed input/output
schemas in spec/schemas define calculate and cost_scenarios. CAP-009 is the existing
canonical calculator ID; CAP-010 Python remains disabled. The executor is pure code
using Decimal integers as exact reduced numerator/denominator pairs, with a private
256-digit context and Inexact trap. Every reduced component is capped at 60 digits;
the largest cross product is 120 digits. No intermediate approximate division. Final
half-even display uses quotient/remainder; negative zero is canonicalized. Ambient
Decimal precision/rounding cannot change results. No eval/exec, shell, imported expression,
binary floating-point arithmetic, dynamic plugins, external data or currency conversion.

The independent verifier uses Fraction/integer operations and its own expression walk,
unit rules, cost formulas and quotient/remainder rounding. It never calls the executor.
Both validate the closed schemas and numeric bounds; comparison uses canonical JSON to
reject even a forged floating-point scale equal to an integer. Tests include explicit
golden numbers, rational cancellation, signed ties, 100 seeded exact fixtures, 60-digit
boundaries, 64 nodes/depth 8, nonfinite/injection/negative inputs and forged receipt fields.

Supported currency scales are explicit contract constants: JPY 0, RUB/USD/EUR 2, KWD 3.
These are display policies for supplied numbers, not live exchange/tax/financial data.
count/item quantities can be fractional, nonnegative decimal counts; no implicit unit
conversion. Arithmetic add/subtract needs equal units; multiplication requires a scalar
operand; division accepts scalar denominator or equal units yielding scalar. Percent's
rate is scalar. Arbitrary derived dimensions are rejected.

Each cost scenario is one homogeneous batch: fixed_cost_total + quantity *
variable_cost_per_unit. Fixed cost is added once even for quantity zero; unit cost is
undefined at zero quantity. Selling price is optional; no revenue/margin/markup is inferred
without it. Gross margin uses revenue as denominator, markup uses total cost. Zero
denominators are explicit undefined_zero_denominator, and negative profit is valid.
Exact fractions remain in receipts; formatted values never feed later calculations.
Inputs are retained in the admitted immutable plan, and receipts bind their digest.

## Opt-in, execution and inspection

The registry denies CAP-009 unless the existing admitted owner scope contains
experimental_calculator=true. The default provider schemas/prompts omit it. Model
intents cannot add scope or permissions; the model worker derives its tool schema from
the persisted admitted task, not a model-selected flag. Valid opted-in operations are
read, idempotent, five-second bounded workers, with no approval or filesystem/network
effect. Existing scope, admission/inventory, budgets, stop and recovery apply. Saved
scope changes invalidate admission. All M1 write/approval/reconciliation gates remain.

The worker verifies the receipt; the parent independently invokes the verifier again
before Journal.finish. A forged tool result cannot become verified. Evidence projects
metadata in ordinary show views, full checked numeric output only in admitted final
context/explicit owner calculation output. Private tasks keep source values out of stdout,
stderr, events and diagnostic evidence; full canonical values stay in the local journal.
The existing 6000-byte model envelope is unchanged: large evidence may yield honest
receipt-only partial output, while complete verified numbers remain stored. LLM narrative
is not numerical authority. All calculation inputs, including embedded units, are data.

Initialize a synthetic root, then use the packaged example input from an installed wheel
or copy a reviewed example into a local input file. Explicit owner CLI commands:

```
python -m personal_agent --root ABSOLUTE_TEST_ROOT calculate --project example --experimental-calculator --input calculation.json
python -m personal_agent --root ABSOLUTE_TEST_ROOT cost-scenarios --project example --experimental-calculator --input scenarios.json
python -m personal_agent --root ABSOLUTE_TEST_ROOT run --project example --experimental-calculator "Calculate 0.1 plus 0.2 with scalar units, scale 2, half_even; cite the verified receipt."
```

Without the opt-in flag, numerical CLI commands deny. Input JSON is read with a 4096-byte
cap, duplicate keys and linked paths denied, then admitted as owner input. No nested path
or URL is dereferenced. Deterministic CLI uses a fixed in-process planning/final provider
and the normal journal/worker/verifier; no LLM/network inference occurs. Its two provider
calls still consume existing model-call budget counters (they are logical provider calls,
not two Qwen calls); model_inference_used=false makes that explicit. --private-intent
withholds numeric input/output from diagnostics. An oversized final projection can be
partial even when numeric execution is verified; no full-analysis claim is fabricated.

Crash before acknowledgement recovers a calculation as pending read, bounded by the old
three-attempt policy. Crash after verification reuses its exact saved receipt without
dispatch. Real child-process exit/timeout tests verify both paths; no needs_reconciliation
or owner approval is manufactured for pure computation. SQLite remains v4, no migration.

## Evidence and remaining work

Run full Windows/Ubuntu unittest suite, schema/traceability/combined DAG, Ruff, wheel and
tools/verify_package.py. New tests: test_calculator.py, test_calculator_integration.py.
The installed-package check includes real CLI -> worker -> verifier, golden output and
forged-result rejection outside checkout. HTTP stub tests exercise the selected adapter's
schema-constrained intent and final evidence; they are not live Qwen evidence. Fresh live
availability/outcome and exact SHA/CI are recorded separately in the PR and delivered logs.

The first installed-wheel live attempt exposed Ollama's inability to resolve a recursive
`$ref` under a nested `$id` (smoke passed, workflow blocked with ollama_http_error). The
provider schema now lifts the same closed node definition to the response root; canonical
tool schemas are unchanged. A new schema regression and a fresh installed-wheel live
smoke/calculation then passed, four model calls, exact 0.30 receipt, no approval. The failed
attempt is retained in the delivered evidence and is not counted as a pass. The optional
`tools/verify_calculator_live.py` uses a fresh synthetic root and nonzero/FAILED on error.

Before TASK-011 completion: independent review, dependency/acceptance resolution and any
remaining live-model reliability gaps. This implementation covers a bounded scalar/batch
subset, not arbitrary financial models, mixed-currency conversion, complex units, multiline
materials or editable office documents. Shared schema/unit policy is still a common verifier
assumption; independent arithmetic does not prove arbitrary user intent was interpreted
correctly. Same-account code/DB trust and existing M1 data risks remain.

Next product order: TASK-012 DOCX/PDF with preserved originals, structure/diff and actual
parser safety gates; then TASK-013 editable XLSX with verified formulas AND cached results.
Neither is implemented here. No payment, order, external send, deployment, production data,
secrets, Ollama/Windows setting change, merge, retarget or rebase.
