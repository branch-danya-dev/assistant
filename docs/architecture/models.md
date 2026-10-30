# Inference providers and resource policy

## Selected baseline (ADR-015: accepted)

- **Primary local model:** Qwen3.5 9B, Ollama tag `qwen3.5:9b`.
- **Provider:** Ollama, loopback endpoint `http://127.0.0.1:11434`.
- **Source of truth:** `spec/model-config.json`; example environment: `.env.example`.
- **Model files:** `G:\Assistant\models\ollama` via Windows User-level `OLLAMA_MODELS` (ADR-016; `spec/storage-config.json`). Restart Ollama after changing that variable, and configure it before the model pull.
- **Initial context budget:** 8,192 tokens, configurable later by operational need and available memory. A model's advertised 256K maximum is **not** our deployed context target.
- **Selection rationale:** explicit owner preference, text/vision and tool-capable model family, practical fit for RTX 5070 Ti 16 GB VRAM. Model weights alone do not implement tool execution or vision parsing.
- **No model tournament:** do not run A/B tests, model-ranking experiments or request selection benchmarks as a prerequisite. Record the resolved Ollama digest and quantization when actually installed for reproducibility.
- **Implementation state:** planning only; there is no installed/verified model or working runtime in this repository.

## Startup and smoke verification (not comparative model testing)

Future adapter task `TASK-006` must check that Ollama is reachable, `qwen3.5:9b` is available, a small text prompt succeeds, and one synthetic structured tool-call is parsed and **not executed** without policy authorization. Report runtime availability/VRAM constraints without treating this as model ranking. Do not claim success before testing on the host.

For a Windows host with Ollama installed, the eventual manual installation command is:

```powershell
ollama pull qwen3.5:9b
```

Do not interpret the command above as proof that anything has been installed remotely.

## Core provider contract

Inference port isolates text responses, structured tool calls, optional image inputs, token metrics, errors and provider capabilities. Persona, permissions, task state, user data and memory live **outside** the selected model. Keep a replaceable adapter interface without implementing other local models unless owner requests it.

## Operating modes

- `local`: inference on host, no cloud inference; network-capable tools governed separately.
- `hybrid`: optional consent-gated cloud escalation in later milestones; no implicit privacy-sensitive payload transmission.
- `cloud`: separately approved owner-selected provider in the future, not part of the M1 default.

Initial routing has a single selected local model; no confidence-based model-switching or automatic alternative selection is required.

## Resource policy

Host target: RTX 5070 Ti (16 GB VRAM), Ryzen 5 7600X, 32 GB RAM, Windows. Observe RAM/VRAM and context costs. Model weights, context cache and GPU applications compete for GPU memory. Resource manager may unload idle models while the scheduler and memory store continue running. Do not interrupt an active irreversible operation. Store no private prompts in telemetry.

## Reference

Official Ollama catalog: https://ollama.com/library/qwen3.5
