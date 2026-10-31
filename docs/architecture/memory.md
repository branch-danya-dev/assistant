# Layered memory architecture

## Physical storage

The accepted local persistence root on the owner Windows host is `G:\Assistant\data`, with `db/`, `history/`, `memory/`, `identity/`, `skills/` as separate partitions. Store only root-relative references and use an explicit `ASSISTANT_ROOT` override for migration. See `spec/storage-config.json` and `docs/architecture/storage.md` (ADR-016). The Git checkout is separate from private data.

## Storage partitions
1. Working context: bounded per-session/task; ephemeral and not the sole source of truth.
2. Event history: append-only tool/action/decision events with evidence references.
3. Semantic facts: typed facts with source provenance, confidence, effective timestamps, supersession.
4. Project records: requirements, designs, dependencies, decisions, conflicts and open issues, with `project_id` isolation.
5. Procedures/skills: reusable vetted workflows with versions, inputs, permissions and evaluation history.
6. Source archive: original documents/messages/files when explicitly permitted; links/hashes and retention metadata.

## Retrieval
Scoped query -> ACL/project filter -> FTS candidate retrieval -> optional embedding similarity -> rerank -> source/provenance validation -> bounded context assembly. Never include arbitrary entire chat archive, and never cross project boundaries without an explicit reason and authorization.

## Mutation
A new fact does not erase old conflicting facts. It can `supersede` a prior record while preserving the historical decision chain. Distinguish `reported`, `observed`, `inferred` and `verified` evidence statuses. Model-generated summaries are not primary sources.

## Governance
User can inspect, edit, export and delete records. Implement retention and backup policies; deletes must account for derived indexes and backups where feasible. Do not commit private runtime data to Git. Sensitive data stays local unless scoped user approval explicitly allows egress.

## Initial implementation
SQLite tables + FTS5, separate interchangeable embedding index. Performance limits are to be validated on the target host; PostgreSQL is not a baseline dependency.

## Data contract
`spec/schemas/memory-record.schema.json`. Every material claim in a final output should be traceable to source/evidence where available.

## Memory lifecycle baseline (REQ-054, TASK-041)

Retention classes: `durable` (explicit user preferences, sourced important decisions), `project` (active scoped records), `temporary` (intermediate retrieval/context and scratch), `archive` (readable source/history) and `user_managed` (owner-controlled). Do not delete durable/provenance records merely because context is full. Temporary records may expire according to future owner-visible retention settings; search indexes are rebuildable from canonical records.

Apply project ACL and privacy classification **before** lexical/vector ranking and prompt assembly. Automatically extracted facts carry source/evidence_status; unverified inference does not supersede a verified owner decision. Track changed facts with `supersedes`, effective times and original source pointers. Record TTL for temporary material, and provide explicit privacy-export/delete machinery by M3.

M1 lexical retrieval additionally filters current admission expiry and matching inventory before
ranking/limits, then independently validates each whole-record receipt/provenance. A denied
source does not block other matches. Full candidate/history checks are bounded to 256 per call;
exhaustion is an explicit error, never silent truncation. Storage/internal errors still abort.
See [implemented search contract and risks](../engineering/m1-trust-inventory.md#mixed-admission-search-follow-up-review-5722293592).
