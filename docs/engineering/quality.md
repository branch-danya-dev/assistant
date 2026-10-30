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

## Selected-model smoke and functional checks (ADR-015)
The owner selected `qwen3.5:9b` without comparative LLM testing. Do **not** require A/B model comparisons or automated model rankings. Test that the selected Ollama adapter can load, complete a prompt and produce a parseable synthetic tool call. Continue to validate task outputs, authorization, numerical correctness and security with `spec/scenarios.json`. Record selected model/tag, resolved digest/quantization when installed, and environment details only for reproducibility. Functional acceptance and security regression are mandatory even though model selection comparisons are not.
