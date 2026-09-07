# LP-UI-026 — Admin: lender overlay editor

- **Ticket:** LP-UI-026
- **Epic:** Ledger redesign → Epic D (Admin)
- **Status:** Completed
- **Date:** 2026-08-30
- **Depends on:** LP-UI-025
- **ADR:** none new.

## The screen was making a false claim

The editor's own introduction read:

> Editing a threshold changes what enforcement uses for this lender.

**That is not true today.** The rule engine builds its overlays from
`SAMPLE_OVERLAYS` and `STARTER_OVERLAYS` — hardcoded dicts keyed by slug in
`verification/registry.py` — and nothing anywhere constructs a `LenderOverlay`
from `lenders.lender_overlays`, the column this editor writes. LP-87 built the
editor half of ADR-193's deferral; the reading half is not built.

Verified before writing a word of the replacement, not assumed: `default_registry()`
composes from those two dicts, and `lender_overlays` appears nowhere in the engine.

So the screen now says what is actually the case:

> **Recorded, not yet applied.** Overrides saved here are stored and audited, and
> the rule engine does not read them yet — it runs the investor defaults for every
> lender. Nothing on a loan file changes until that wiring lands.

A screen that tells an admin their change is in force when it is not is the worst
thing this editor could do. The notice carries a code comment saying to **delete it
when the column is wired** — it is a statement about today, not a permanent caveat.

The gap itself is raised to the user; wiring the column into the registry is a
sequencing decision about LP-87's remaining half, not something a UI ticket
settles.

## The audit was losing removals

Found on screen, not in a test. The change history read:

> Avery Stone **saved the overlay with no threshold changes**

for the edit that had just *deleted* an override. `field_changes` iterated
`after.items()` alone — its docstring said so — so a key present before and absent
after produced nothing. The audit trail, which exists to record what happened,
held no record that the override was ever removed.

Fixed at the shared function rather than at the call site, because a second
definition of "what changed" is the defect this epic keeps finding. It now covers
**both** key sets. The other three callers — property, stated financials,
loan-file edits — build `before` from `after`'s own keys, so their key sets are
equal by construction and the union is the same set; 383 of their tests pass
unchanged, and a test pins that equivalence.

## The three criteria

- **Base and effective side by side.** They were a caption under the rule id
  (`base 43 → 45`). Now two columns, *Agency base* and *This lender*, so the effect
  of a change is legible without comparing a value against a footnote.
- **Change history readable as prose, not a diff dump.** It rendered
  `conv.income.credit_doc_age: 90 → 120` in mono beside a raw ISO timestamp. Now
  sentences: who, what moved, and why, with a relative time. Setting, moving and
  removing an override are three different things an admin does for three reasons,
  and a `from → to` renders all three identically — so each has its own phrasing.
- **Reason required; audit entries unchanged in shape.** The reason gate is
  untouched. The **stored** shape is untouched: the label and the actor's name are
  resolved on the way out, in the view, never written to the blob.

## Two things resolved on the read side

`field_label` comes from the base rule index the editor already resolves against;
a rule the catalog no longer carries yields `None` and the prose falls back to the
id, which at least identifies what moved. `actor_name` comes from
`resolve_user_names` — extracted from LP-UI-021's override attribution so the
calculator lines and this audit trail cannot give one person two names. An unknown
actor reads "Someone"; a placeholder in an audit trail is a name nobody checked.

## A copy defect the screenshot caught

Rule descriptions are full sentences, so embedding one produced:

> set Income/credit documents are no more than 4 months old on the note date. to 90.

The trailing stop is trimmed and the name quoted, so it reads as the name of a
thing rather than a clause that ended early.

## Tests

712 frontend and the backend suite green. Five mutations verified to fail: the
not-applied notice removed, set/remove collapsed into one phrasing, an unknown
actor given an invented name, the base column dropped, and `field_changes` back to
iterating only `after`.

## Review pass — the fix landed two layers below the bug, and nothing tested the layer between

Reviewed on request from the session running the epic. One gap closed; both
judgement calls confirmed, one of them by independent verification rather than
by agreeing.

### The shared-function change is safe, verified caller by caller

This was the right thing to ask for a second pair of eyes on, and the reasoning
holds. Checked each of the three other callers directly rather than by grep:

- `api/property.py:77` — `provided = payload.model_dump(exclude_unset=True)`,
  `before = {field: getattr(property_obj, field) for field in provided}`. Key
  sets equal by construction.
- `api/stated_financials.py:100` — same shape, `before` built from `provided`.
- `services/loan_files.py:418` — `changed_fields = set(provided.keys())`, then
  **both** `before` and `after` built from `changed_fields`. Equal.

In all three the union `{*before, *after}` is the same set the old
`sorted(after)` iterated, so the change is a no-op for them and only the overlay
caller — the one with genuinely asymmetric key sets — behaves differently. Fixing
it at the shared function rather than the call site was correct: a second
definition of "what changed" is the defect this epic keeps finding.

### `update_lender_overlay` had no test at all

The fix is in `field_changes`, guarded by
`tests/services/test_field_changes_removals.py`. The **defect** was in the audit
trail on screen, produced by `update_lender_overlay` — and nothing in the suite
called that function. Searched by name across `tests/`: no callers, and no
overlay file under `tests/api/`.

That is the LP-UI-011 shape once more: the helper is tested, the wiring is not. A
later change to how the writer builds `before` and `after` reintroduces exactly
the visible defect with the shared function still correct and its test still
green.

Seven tests now cover the writer at the layer the bug was seen: a removal is
recorded with its `from` value, an addition and an edit record from→to, a removal
alongside an unchanged survivor records only the removal, the trail appends
rather than replaces, another company's lender is not found, and an unknown
`rule_id` is refused.

Mutation-checked at **both** layers, which is what shows the new tests earn their
place: iterating `after` alone fails the helper's tests and the writer's;
building `before` from `after`'s keys inside the writer leaves the helper
correct and its tests green, and fails only the new ones.

### A correction to my own method, recorded because it is the epic's own lesson

The first mutation run I did here reported "59 passed" and I read it as *not
caught*. The selection was `-k "activity_log or overlay"`, which does not match
`test_field_changes_removals.py`. The guard existed and my run could not see it.

That is precisely the hazard the hand-off named two tickets ago — *a run that
finds no tests is indistinguishable from one that finds no failures* — arriving
by a different route: not a wrong path, a filter that silently excluded the only
file that mattered. The habit that catches it is reading which tests ran, not
only how many passed.

### Confirmed, not changed

- **The false-claim fix.** "Editing a threshold changes what enforcement uses for
  this lender" was a false statement on screen, and verifying
  `default_registry()` first rather than taking the previous review on trust is
  the right instinct. "Recorded, not yet applied" with a comment saying to delete
  the notice when the column is wired is the correct shape: a statement about
  today, marked as temporary, rather than a caveat that outlives its cause.
- **The actor-name split.** Right. `build_overlay_view` stays synchronous and
  touches no database, so the base-against-effective composition is testable
  without one; `attach_actor_names` is I/O and belongs outside it. And
  `resolve_user_names` has one definition, in `override_attribution.py`, imported
  by the overlay admin — verified, so the calculator lines and the audit trail
  cannot give one person two names.
- **The trailing-stop copy defect.** Only a screenshot finds *"set Income/credit
  documents are no more than 4 months old on the note date. to 90."* — no
  assertion would have been written for a sentence nobody expected to be a
  sentence.

### Verification

Backend `ruff` and `mypy` clean over 449 files, **6,041 pass** (from 6,034) with
the two known `.env` failures. Frontend `tsc` clean, **712 tests**.

| mutation | result |
| --- | --- |
| iterate `after` alone in `field_changes` | 4 tests fail (both layers) |
| build `before` from `after`'s keys in the writer | 2 tests fail (writer only) |
