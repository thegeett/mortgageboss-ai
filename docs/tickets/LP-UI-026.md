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
