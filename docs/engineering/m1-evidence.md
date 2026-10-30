# First M1 slice — implementation evidence

This is a partial M1 delivery, not milestone acceptance. Every fixture uses synthetic data.

## Storage and journal

`tests/test_storage.py`: explicit root, unsafe path rejection, migration idempotence/future-version
refusal, consistent SQLite backup/restore, SCN-009 relocation, exclusive executor lock.
`tests/test_journal.py`: schema-valid events, durable transitions, one-use exact approval,
expiry/digest mismatch, persistent stop, forged evidence rejection, budget exhaustion,
SCN-010 real child-process exit after a simulated effect and before acknowledgment.
Unknown effects require reconciliation and a fresh task; no replay of the original action.

Local Windows Python 3.12.10: spec validator and 20 tests passed at this implementation boundary.
The live Ollama API was unavailable during initial inspection; live-model acceptance remains open.

## Implementation choices within accepted ADRs

- Reuse the already approved `jsonschema` package at runtime, pinned to tested `4.26.0`,
  so model/record validation uses the actual canonical contracts. No additional runtime package.
- Package builds copy canonical `spec/` into package resources; editable development reads `spec/`
  directly. There is no independently maintained second set of schemas.
- One OS-released executor lock serializes running/recovery commands. Read-only inspection and
  owner stop remain available through other SQLite connections. No background daemon is installed.
- Version 1 migration is transactional. Rollback means stop the app and restore a verified
  pre-upgrade online backup; no lossy automated down migration.
- Event payloads contain codes, IDs and digests. Private task intent, tool results and arguments
  live only in the local database, outside Git and diagnostic logs.
