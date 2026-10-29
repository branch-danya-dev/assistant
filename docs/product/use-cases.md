# Reference workflows

`spec/scenarios.json` is the canonical executable-acceptance checklist. This file gives narrative context.

## Supplier comparison (SCN-001)
Read user-approved requirements from project memory -> search public pages -> retain citation/source URL, capture timestamp and any units/currency -> normalize comparable offers only when conversion inputs are available -> create table with unknowns explicitly marked -> prepare draft outreach. **Never contact suppliers or place an order automatically.**

## Spreadsheet costing (SCN-002)
Collect price/quantity assumptions -> calculate with Decimal or another verified numerical tool -> write editable input cells and formulas -> recalculate/validate independently -> report assumptions, formula checks and margin scenarios. Do not treat unsourced estimates as quoted prices.

## Document revision (SCN-003)
Copy original to controlled workspace -> extract structure -> apply narrowly scoped edits -> produce diff -> validate no sections disappeared -> request approval for overwriting originals or sharing documents externally.

## Project continuity (SCN-004)
Locate scoped, sourced decision records -> provide current decision and superseded alternatives -> avoid contaminating other project contexts -> surface missing or contradictory evidence rather than fabricating a rationale.

## Agent task lifecycle (SCN-005)
Create an auditable task plan -> authorize each side-effect -> execute bounded steps -> capture structured results and proof -> checkpoint -> stop on unmet authorization -> resume safely from persisted state, never blindly rerun non-idempotent actions.

## Deficient tool workflow (SCN-006, later)
Identify missing capability -> search existing approved tools -> propose candidate or draft implementation in sandbox -> test with fixtures -> generate diff and risk analysis -> require owner review before installing into trusted tool registry.
