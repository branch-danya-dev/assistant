# Layered memory architecture

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
