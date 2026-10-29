# Inference providers and resource policy

## Core contract
The model provider interface separates `complete`, `structured_output`, tool-call formatting, token/cost metrics and provider capability discovery. The provider is not the agent: identity, task state, permissions and memory belong elsewhere.

## Proposed modes
- `local`: no cloud inference; tool network access separately governed.
- `hybrid`: local-first, optional explicit cloud escalation by policy/sensitivity/cost.
- `cloud`: explicit owner-selected cloud model for high-reasoning requests; no silent private-data egress.

## Router inputs
Complexity and task type; required modality and tool syntax; context length; available RAM/VRAM; latency/cost budget; privacy classification; current provider health. A model should **not** be trusted to estimate its own correctness alone; router escalation needs benchmark-derived thresholds and/or verified tool failures.

## Host and evaluation
Target host RTX 5070 Ti 16 GB VRAM, Ryzen 5 7600X, 32 GB RAM. A quantized ~8–14B local model is a reasonable benchmark candidate, not a guaranteed choice. Measure first-token latency, tokens/s, RAM+VRAM usage, long-context performance, tool-call validity and task completion. Large contexts can push memory beyond the weight size. Avoid relying on arbitrary model-size rules as performance guarantees.

## Resource manager
Track model residency and unload idle models when VRAM is needed by other applications. Do not interrupt active file writes or send actions when unloading inference. Background scheduler and memory DB must remain operable when LLM is unloaded. Preserve observability without harvesting sensitive payloads into telemetry.
