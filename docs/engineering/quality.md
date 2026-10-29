# Quality, evaluation and evidence

## Test layers
1. Spec validation: JSON parse, unique IDs, cross-links, statuses, file map and safety invariants.
2. Unit: deterministic routing/policy, typed tool args, numerical correctness, memory conflict rules.
3. Integration: sandboxed adapters, persistence and fault injection.
4. End-to-end scenario: verifiable artifacts plus audit and approval behavior.
5. Security regression: injected webpages, forged tool outputs, suspicious document instructions and unauthorized egress.
6. Performance: tokens/sec, p95 latency, VRAM peak, task completion time and CPU/RAM with target GPU.

## Definition of done
Requirement linked -> tests written -> correct behavior observed -> verification evidence stored -> security constraints and error paths checked -> docs/specs synced. Never mark capabilities implemented from an architecture proposal.

## Numerical/document tests
Use fixture-based expected outputs; evaluate Excel formulas *and* computed values; test DOCX preservation and PDF layout; compare source citations for research; use decimal arithmetic for monetary cases; include idempotency on retry.

## Model benchmark corpus
Include tasks from `spec/scenarios.json` with expected results, tool-call validity and evidence/side-effect rules. Record model name, quantization, context size, machine profile, versions, elapsed time, cost, success and confidence intervals where meaningful.
