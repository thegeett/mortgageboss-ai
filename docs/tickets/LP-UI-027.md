# LP-UI-027 — Overlay blast radius (backend)

- **Ticket:** LP-UI-027
- **Epic:** Ledger redesign → Epic D (Admin)
- **Status:** Completed
- **Date:** 2026-08-30
- **Blocks:** the rail in LP-UI-026 — see "What this does not include"
- **ADR:** none new.

## Summary

`POST /admin/lenders/{id}/overlay/blast-radius` takes a **proposed** overlay and
answers which of that lender's open files would newly block, newly clear, or move
a rule without changing the file's overall answer. Read-only: no writes, no runs
enqueued, nothing recorded.

An overlay moves every file at a lender, which is exactly why an admin should see
the consequence before committing rather than after.

## Why it computes instead of reading stored findings

The ticket says "estimated against each file's last completed run". Building it
that way would have returned **"no files affected" for every proposal**, which is
the most dangerous possible answer — it reads as reassurance.

Measured, not assumed:

- **Zero findings exist for any overlay-able rule.** `conv.*`, `fha.*` and sample
  rule ids have produced **0** findings. Every finding in the database is
  `cross_source.*`, `xsrc.*`, or a governed short id (CR-8, IN-9…).
- **The engine that reads overlays has no production caller.**
  `services/verification_engine` is the only caller of the overlay-aware
  `evaluate()`, and nothing imports it — a fact the codebase already records, in
  `finding_source_matching.py:193`: *"`verification_engine` has no caller"*.

So the estimate resolves each file's rules, swaps the proposed thresholds in
through `VerificationRule.with_condition` — the model's own overlay mechanism, so
a proposal is applied exactly the way a real overlay would be — and evaluates the
**pure** `evaluate()` twice, then diffs. That works today regardless of the wiring,
because it computes rather than reads.

## It reuses the engine's own definitions

"Blocking" comes from `_SEVERITY_TO_STATUS` and the same
`RED`/`YELLOW` pair `finding_blocking.py` uses. The estimate and a real run must
agree about what blocking means, or the number is worse than no number.

`applies_today: False` is on the response. The overlay column is not read by the
registry, so a screen showing this must not imply the change takes effect on save.
When the wiring lands, that flag becomes true and the caveat goes with it.

## Three states, not two

`newly_blocking` and `newly_clearing` are the ticket's question. `changed_only` is
the third real case — a rule flips but the file blocks either way — and folding it
into "newly blocking" would overstate what a change does.

## What this does not include

The ticket says it **blocks the rail in LP-UI-026**, and the rail is not built
here: this ticket's files and criteria are the endpoint. The editor now has data to
show a blast radius; wiring the rail is a UI change to a shipped screen, and it
should be its own commit so the endpoint can be reviewed on its own terms.

## Tests

11 service tests and one at the API layer, plus the full suite: **6,053 pass**
(from 6,041), ruff and mypy clean.

**Eight of the eleven would pass against an estimator that always returned empty
lists.** The three that would not are the load-bearing ones: a conventional file at
48% DTI, against `conv.dti.back_end_max` (`<= 50`, red). Proposing 45 newly blocks
it; a file at 53% proposed 55 newly clears; and proposing 49 against 48% moves
nothing, because the estimate reports a file when the **verdict** changes, not
whenever a number does.

Five mutations verified to fail, including the always-empty one — the trap the
first eight tests could not see.

The API-layer test is deliberate: the LP-UI-026 review found a defect guarded in a
helper with the calling layer untested, so this endpoint is tested where it is
exposed, including that the overlay is untouched afterwards and a cross-company
lender is a 404.
