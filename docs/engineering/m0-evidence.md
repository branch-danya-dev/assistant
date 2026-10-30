# M0 evidence — 2026-10-30

Starting point: `c1a0079d81b4b641568536ef8bc6d16ea8d65c22`.
Baseline CI verified through GitHub job results: [run 41041028122](https://github.com/branch-danya-dev/assistant/actions/runs/41041028122),
both `validate (windows-latest)` and `validate (ubuntu-latest)` succeeded.

- TASK-001 / TASK-039: `tools/validate_specs.py`, `tests/test_specs.py`, JSON Schema 2020-12 and the two-platform CI matrix.
- TASK-002: `docs/architecture/security.md` and `docs/engineering/threat-fixtures.md` define injection, exfiltration, irreversible effects, stop and recovery boundaries.
- TASK-003: `tests/fixtures/acceptance.json` contains concrete synthetic inputs, expected outputs, gates and adverse cases for SCN-001..005; `tests/test_fixtures.py` checks the rubric.
- TASK-040: the same fixture catalog maps TH-001..009 to named runtime regressions to be implemented in M1. M3 generated-code isolation remains disabled until its own sandbox implementation and tests exist.

Current repository setup instructions already reference `branch-danya-dev/assistant` and distinguish specification from implementation. No real user records or credentials are test inputs. M0 completion does not certify any running agent or the later office/browser integrations.

Local Windows Python 3.12.10: spec validator PASS; 8 unittest tests PASS.
