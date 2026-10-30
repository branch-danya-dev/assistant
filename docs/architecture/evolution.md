# Learning and evolution: improve the agent, not automatically its weights

Three independent growth mechanisms:

1. **Knowledge growth:** sourced, scoped, versioned facts and decisions become retrievable. No training required.
2. **Skill growth:** successful verified workflows become versioned procedures/templates; missing-capability detection can propose new tools. No weight training required.
3. **Model adaptation:** optional future curated dataset and offline LoRA/QLoRA experiments, gated by objective benchmark evaluation, rollback and owner signoff. Not part of first releases.

## Delivery split

M3 (TASK-042) captures **non-executable** skill proposals distilled from verified task outcomes. M4 (TASK-021) provides reviewed sandbox creation, testing and owner approval for executable skills. These are different trust stages; recording a candidate never activates code. Automatic weight fine-tuning is not part of the delivery baseline, and the optional M4 task documents feasibility only.

## Skill lifecycle
`candidate -> sandboxed -> tested -> review_required -> approved -> active -> [deprecated | revoked]`.

- A candidate is a *proposal*, not executable trusted code.
- Sandbox may generate source and tests but cannot modify agent core or production store.
- Tests require both functionality and security cases.
- Activation requires an authorized human-approved promotion with pinned version and provenance.
- Record outcomes, error types, review decisions and evaluation data to compare versions.
- Never auto-save every interaction as reusable skill; deduplicate and validate utility.

## Success measurement
Use deterministic task verifiers, human outcome labels and replayable benchmark fixtures. The agent's own self-assessment is insufficient evidence. If a new workflow fails comparison, revert or retain as an experimental candidate.
