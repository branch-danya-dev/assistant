# Persistent persona and user preferences (M1)

**Goal:** retain one configurable assistant identity across process restarts and model/provider changes without claiming sentience. Identity is **data in local storage**, not a property of the Qwen weights.

## Canonical contract

`spec/schemas/persona.schema.json` defines a versioned persona record, with required `persona_id`, `version`, `core`, `preferences`, `provenance` and `updated_at`. Store within `data/identity` under the effective `ASSISTANT_ROOT`. Every update keeps a previous version and source/actor. A mock model replacement must leave record IDs, version and preferences intact (SCN-011).

## Stable vs adaptive

- **Stable, owner-controlled core:** name, principles, tone defaults, refusal to pretend a tool executed, authority boundaries and privacy policy. Model must not rewrite it.
- **Adaptive user preferences:** presentation choices and task conventions can be recorded as sourced user-provided or inferred preferences. Inferred entries are non-authoritative suggestions until accepted when materially important.
- **Contextual behavior:** work/report style may differ from conversational style, but math, tool permissions and accuracy checks do not change with personality.
- **Memory distinction:** persona data is separate from project decisions, untrusted web content, task history and tool output.

## M1 acceptance

TASK-025 must implement inspectable/versioned initial persona storage, bounded prompt context and reloading after restart/provider replacement. TASK-028 later adds user-facing editor and restoration UX.

## Privacy

Persona and preference records can be sensitive. Do not export them to cloud or external tools without owner approval and data classification. Never commit real user personality/memory files into this public repo.
