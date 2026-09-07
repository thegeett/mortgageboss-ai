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

## Review pass — a third definition, under a comment saying it was not one

Reviewed on request from the session running the epic. One defect, the
deviation upheld, and the two remaining calls confirmed.

### `_blocks` restated the blocking severities

Asked for directly, and there was one. The docstring on `_blocks` read
*"`_SEVERITY_TO_STATUS` and `_BLOCKING_SEVERITIES` are the engine's own, not a
second opinion formed here"* — and the line beneath it wrote
`(FindingStatus.RED, FindingStatus.YELLOW)` inline.

`_SEVERITY_TO_STATUS` genuinely is imported. `_BLOCKING_SEVERITIES` was not.
That is LP-UI-021's `INCOME_VARIANCE_PERCENT` exactly: a copied constant under a
comment asserting it was imported, agreeing with its source only until someone
edits one of them. It matters more here than it did there — this number is a
blast radius, and its whole purpose is to predict what a real run would do.

Now imported from `finding_blocking`, where the writer's own query reads it.

### The test I wrote for it did not test it

Recorded because it is the epic's own lesson landing on the reviewer. The first
version asserted `overlay_blast_radius._BLOCKING_SEVERITIES is
finding_blocking._BLOCKING_SEVERITIES` — which pins that the constant is
IMPORTED and says nothing about whether `_blocks` uses it. A restatement at the
use site passes it, which I confirmed by mutating exactly that.

It is now behavioural: for every severity the engine maps, `_blocks` must agree
with `finding_blocking`'s answer. Mutated with a genuinely different pair
(`(RED,)` alone) and it fails.

The limit is worth stating rather than papering over: a restatement of the
IDENTICAL pair is behaviourally indistinguishable, and no test can catch it. What
the import buys is that the next edit to one moves both.

### The deviation from the stated basis is upheld

"Estimated against each file's last completed run" cannot be built, and the
reasoning was verified rather than accepted:

- `finding_source_matching.py:193` says it in the codebase's own words —
  *"`verification_engine` has no caller"*.
- Confirmed independently: the only importer of `verification_engine` anywhere in
  `app/` is now this estimator itself.

So an estimate reading stored findings has nothing to read, and would return
"no files affected" for every proposal. That is the most dangerous answer a blast
radius can give, because it is indistinguishable from a correct one and reads as
reassurance — the same failure mode as a mutation run that finds no tests, in a
place where an admin acts on the result.

Evaluating the pure engine twice and diffing is the right substitute: it answers
the question the ticket asked, with today's mechanism, and it will keep working
when the column is wired.

### Confirmed, not changed

- **Eight of eleven tests passing against an always-empty estimator.** Noticing
  that unprompted is the most valuable thing in this hand-off. The three that fix
  it are the right shape — a file at 48% against a `<= 50` rule, with a proposal
  that newly blocks, one that newly clears, and one that moves nothing — and M1
  being exactly the always-empty estimator is the correct mutation to have
  chosen.
- **`applies_today: False` on the response rather than only in a docstring.**
  Right, and it is the same principle as the notice in LP-UI-026: a consumer
  cannot render "your change will do X" without also holding the fact that it
  does not apply yet. A docstring is read by whoever edits the endpoint; the
  field is read by whoever builds the screen.
- **Not building the rail here.** Right. The endpoint is this ticket's files and
  criteria, and wiring a shipped screen deserves its own commit so the endpoint
  can be reviewed on its own terms. Splitting on the reviewable unit is the same
  call LP-UI-015 made by taking the backend before the UI.

### For the user's pile

The hand-off's flag is correct and worth carrying up rather than filing: this is
the third distinct piece of the overlay gap. The column is unread by the engine,
the engine that reads overlays has no caller, and no finding exists for any rule
an overlay can target. The estimate works around all three, and a feature
computing what *would* happen while nothing makes it happen is a sequencing call
above the ticket.

### Verification

`ruff` and `mypy` clean over 450 files, **6,055 pass** (from 6,053) with the two
known `.env` failures. No frontend changes.

| mutation | result |
| --- | --- |
| a different blocking pair at the use site | 1 test fails |
