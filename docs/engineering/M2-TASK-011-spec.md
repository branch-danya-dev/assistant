# TASK-011 — experimental deterministic calculator

Canonical links: CAP-009, REQ-026/039, SCN-002 (numeric subset), TASK-011 depends on
TASK-009. Owner instruction of 2026-10-31 authorizes an isolated draft stacked branch
after M1 audit remediation passes. It does not close TASK-009/M1 or approve ADR-025
OD-1/2/3. The experiment is disabled by default; no release, merge or main integration.
CAP-010 arbitrary Python remains disabled. No new dependency is required.

## Closed numeric contract

CAP-009/calculate accepts a typed expression tree: literal, add, subtract, multiply,
divide, negate, percent (value * rate / 100). No expression strings, code, eval, shell,
imports, file/network references or model-provided permissions. Decimal strings only:
optional minus, 1–18 integer digits, up to 6 fractional digits, no exponent, leading
zeroes, NaN, Infinity or JSON floats. Scale is an integer 0–6, rounding is half_even.
Units are explicit closed objects: scalar, count/item, or currency with one supported
code (RUB/USD/EUR/JPY/KWD). No implicit currency conversion. Arithmetic units obey
add/subtract equality, scalar multiplication/division and equal-unit division to scalar.
Percent rates are scalar. Currency display scale is explicit: JPY 0, RUB/USD/EUR 2,
KWD 3. Non-money scalar/count scales are explicitly chosen.

Bounds: input 4096 UTF-8 bytes, 64 nodes, depth 8, reduced exact numerator and denominator
at most 60 decimal digits each, output 8192 UTF-8 bytes, tool worker 5 seconds. Intermediate
Decimal integer arithmetic is exact under a private fixed context; round only final display.
A separate integer/Fraction verifier recomputes exact rational values and half-even rounding
without calling the executor. Forged result, input digest, units, schema or rounding metadata
fails closed. No binary floating point arithmetic. Limits apply before and during evaluation.

Receipts contain contract version, canonical input digest, operation and typed result;
each numeric value includes display value, exact numerator/denominator, scale and whether
rounding occurred. Undefined ratios explicitly report undefined_zero_denominator.
Output schemas forbid additional fields. Verification is trusted code, not a result boolean.

## Cost scenarios: fixed cost belongs to the entire batch

CAP-009/cost_scenarios accepts one to three uniquely named low/base/high scenarios.
Each scenario has quantity (count/item), fixed_cost_total and variable_cost_per_unit,
with one declared currency for the whole request. Optional selling_price_per_unit is an
explicit user input, never inferred. This initial slice handles one homogeneous batch per
scenario. Multiple materials/workbooks and automatic source imports are deferred.

- fixed_cost_total is the fixed cost of the ENTIRE batch/scenario in that currency,
  added ONCE. It is not a per-unit number or a repeated line-item charge.
- variable_cost = quantity * variable_cost_per_unit
- total_cost = fixed_cost_total + variable_cost
- unit_cost = total_cost / quantity only when quantity > 0; otherwise undefined.
- With explicit selling_price_per_unit: revenue = quantity * selling_price_per_unit;
  profit = revenue - total_cost; gross margin % = profit / revenue * 100;
  markup % = profit / total_cost * 100. The denominators differ deliberately.
- At zero revenue/cost the corresponding ratio is undefined, not zero or Infinity.
  Without selling price, revenue/profit/margin/markup are absent (null), not inferred.
- quantity and input amounts must be nonnegative. Zero quantity is valid and total_cost
  remains fixed_cost_total. Negative profit is allowed. Refunds/negative costs/quantities
  are unsupported and rejected. Mixed/unknown currencies and nonfinite numbers are denied.

All totals/ratios derive from exact unrounded inputs. Money is displayed at currency scale;
percentages at 6 places. Display rounding is not fed into further calculations. Receipt
exact fractions expose every rounding difference without adding rounded subtotals.

Golden fixtures: quantity 10, low cost 15/price 20/fixed 30 => cost 180, revenue 200,
margin 10%, markup 11.111111%; base 20/30/50 => 250/300, 16.666667%/20%; high 25/40/50
=> 300/400, 25%/33.333333%. Quantity 0 and fixed 50 => total 50 and undefined unit cost.
Test 0.1+0.2=0.30, 19.99*3=59.97, percent(250,12.5)=31.25, 1/3, signed half-even ties,
large batches, currency scales, zero denominators, cancellation and every budget boundary.

## Integration and evidence

Read/non-mutating, idempotent, no approval. Explicit owner task opt-in is persisted in the
admitted scope; model output cannot enable it. Closed registry and model schemas, bounded
workers, task/project admission, budgets, receipt verification, final evidence projection
and read recovery all apply. Verified actions are not replayed; interrupted reads use existing
retry limits. File writes still require their original exact one-use approval. SQLite stays v4.

Provide a deterministic owner CLI path through the same journal/registry/worker/verifier,
and model intent -> trusted tool -> verified evidence tests. Negative cases include injection,
forged output, extra permission fields, timeout, restart/resume, disabled scope and stale task
admission. Run full Windows/Ubuntu CI, schema/traceability/DAG, Ruff, wheel installation outside
checkout and P0 M1 regressions. Live selected Qwen only if available, separately reported.
TASK-011 remains in_progress until all acceptance and independent review are satisfied;
REQ-039/SCN-002 are not complete without the editable workbook.

Next: TASK-012 DOCX/PDF with structure/diff, protected originals and actual parser safety
gates; then TASK-013 XLSX with editable scenarios, independently verified formulas and cached
results. Neither adapter is implemented in this cycle. Browser, cloud, payments, orders,
external sends, general Python execution and model/OS configuration changes remain outside scope.
