---
id: 2026-05-01-well-shaped-example
task: "Refactor market data sync to use batch upsert"
status: shaping
assigned: codex
complexity: simple
reasoning_effort: medium
model_claude: sonnet
model_codex: gpt-5.6-sol
created: 2026-05-01T10:00:00Z
updated: 2026-05-01T10:00:00Z
acceptance:
  - Batch upsert reduces DB round-trips by at least 50% on 100-symbol load
  - Existing market data sync tests pass
scope_budget:
  net_loc_delta_target: +10 to +30
tags:
  - coordination
priority: 5
---

## Task parameters

_See frontmatter above._

## Scope notes

- [ ] **S1: Replace per-symbol upsert with batch upsert in sync.py**
  complexity: simple
  model_claude: sonnet
  model_codex: gpt-5.6-sol
  Rewrite `MarketDataIngestionService.upsert_quotes` to use SQLAlchemy bulk upsert. Keep the existing interface. Verify with existing test suite.

- [ ] **S2: Update integration test to assert batch count**
  complexity: simple
  model_claude: sonnet
  model_codex: gpt-5.6-sol
  Add a test that asserts a single DB roundtrip when upserting 10 quotes. Run `pytest backend/tests/test_market_data.py -q` to verify.

## Plan

Replace per-row quote upserts with a single bulk upsert statement. Use SQLAlchemy `insert().on_conflict_do_update()`. The interface stays the same; only the internal DB call changes.

## Acceptance test

- Batch upsert reduces DB round-trips by at least 50% on 100-symbol load
- Existing market data sync tests pass

## Claude findings

_No findings yet._

## Subtraction analysis

1. Deletion alternative: Replace the existing per-row loop with the batch call.
2. Orphans: Remove the per-row upsert helper once its only caller is replaced.
3. Net LOC delta target: +10 to +30
4. Retirement: The old loop and helper retire; growth covers the batch regression test.
