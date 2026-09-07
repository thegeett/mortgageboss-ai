# LP-UI-021 — Verification: calculator strip

- **Ticket:** LP-UI-021
- **Epic:** Ledger redesign → Epic C (Core screens)
- **Status:** Completed
- **Date:** 2026-08-30
- **Depends on:** LP-UI-020
- **Carries:** the LP-UI-019 and LP-UI-020 condition — "91 unresolved findings"
- **ADR:** none new.

## The carried condition, and what measuring it turned up

Two reviews running asked that this ticket not close while the calculators' alert
read **"91 unresolved findings"** — a number reconciling with nothing a processor
could see. Measured on `LF-96SV`:

| | |
|---|---|
| governed rule findings | **75** (open 10 · couldn't check 62 · needs review 3) |
| deterministic cross-source (`xsrc.*`) | **3** |
| legacy AI sweep | **13** |
| | **91** |

Two things were wrong, not one.

**It merged three generators into one figure.** LP-375 keeps the governed engine
and the legacy sweep structurally separate, and a single total is that separation
collapsed. `open_in_scope_findings` queries the `Finding` table with no origin
filter — correct for "can this file submit", which is what the function is for,
and wrong as a headline.

**Three of the 91 appear on no screen at all.** The governed tabs read
`rule_findings`; the Old findings tab reads `data.findings`, which is
`ai_cross_source` only. The three deterministic `xsrc.*` findings are in neither
list — and two of them come from `xsrc.income.employer_name_consistency`, the rule
LP-606 retired and the LP-UI-018 review caught the ledger deferring to. They were
counted in a total and displayed nowhere.

The alert now names each system: *"75 rule findings, 3 cross-checks, 13 old
findings unresolved"*. Every part reconciles with the rail beside it, and the
cross-checks are visible for the first time.

## What changed

**Backend** — `FindingBreakdown` + `breakdown_by_system()` in `finding_blocking.py`,
carried on `CalcFindings`, `DtiFindingsStatus` and `LtvFindingsStatus`. Counted
**per system, never as a remainder**: `other` exists so a fourth generator gets its
own visible number. That is the LP-UI-020 review's lesson applied at the point of
writing rather than after — a labelled count derived by subtraction cannot be
wrong about its label, so nothing looks like a claim.

**One alert, where there were three.** `UnresolvedAlert` existed as byte-identical
copies in `calculator-card`, `dti-calculator` and `ltv-calculator`. Fixing the
count in the shared card left the DTI panel still reading "91" on the same screen —
caught on a screenshot, not by a test. Extracted to
`components/file/calculators/unresolved-alert.tsx`.

**Override attribution.** All three override models already record
`actor_user_id` **and** `note`; all three services dropped both, returning
`{field_key: value}`, so the panel could say a figure was overridden but never by
whom. `override_attribution.py` resolves actors in one query for the three, and a
line now reads *"overridden by Priya Desai · auto $583.33"*. An override with no
recorded actor stays a bare "overridden" — a placeholder name in an audit trail
reads as one nobody checked.

## The three acceptance criteria

- **Expanding does not refetch.** Verified by the keys, not by assertion: the tile
  calls `useDti(fileId)` / `useCalculator(fileId, calculator)` and the expanded
  panel calls the same hook with the same key, so React Query serves both from one
  cache entry. Same argument LP-UI-009's rail rests on.
- **Overrides visibly attributed; revert works.** Attribution above; the revert
  control was already there and is untouched.
- **A gated DTI still shows "Gated".** Already satisfied and already commented in
  `calculators-section.tsx` (LP-375) — a required housing input being unknown must
  never render as a fabricated 0. Left alone.

## Tests

674 frontend (from 669) and 6,013 backend (from 6,007), with the two known
`test_model_selection_lp457` failures. tsc, biome, ruff and mypy clean.

Five mutations verified to fail, read as counts: an unknown generator folded into
`legacy` (the residual defect, in the code written to prevent it), governed
identified by origin rather than outcome, the AI sweep counted as governed, the
actor dropped from the line, and a fabricated "unknown" where no actor exists.

Fixtures again: patching `breakdown` in mechanically left `open_in_scope_count: 1`
beside an all-zero breakdown — data that cannot occur, which then made the alert
render nothing. Corrected to be coherent rather than merely type-checking.

## Noted, not changed

- **The 3 cross-source findings are counted but still not listed anywhere.** The
  alert now says they exist; no tab shows them. Surfacing them is a real question
  — they are neither governed outcomes nor the AI sweep — and it wants a decision
  about where that family belongs rather than a tab invented here.
- `CollapsedFindings` auto-expanding an `open` group (carried from LP-UI-020).

## Review pass — a warning with no subject, and a fixture that lied twice

Reviewed on request from the session running the epic. Two defects, four
judgement calls confirmed, and one thing raised to the user rather than filed.

### The alert could render a warning with no subject

Every caller derives `unresolved`, `open_in_scope_count` and `breakdown` from
the same in-scope list, so an all-zero breakdown cannot reach `UnresolvedAlert`
from any real response. It reached it anyway — from a fixture — and rendered
`" unresolved — this calculation may be incomplete"`: a warning whose subject is
an empty string.

The component returns null when it has nothing to name. That converts
"unreachable because three callers' arithmetic stays in step with this
component's" into "unreachable by construction", which is the difference between
a property and a coincidence.

### The incoherent fixture survived in the twin

The hand-off found this and fixed it, and fixed one of two. `open_in_scope_count:
1` beside an all-zero breakdown was corrected in the DTI test and left in the
LTV one — the same pairing, the same file shape, three files apart. This is the
`table-fixed` lesson from LP-UI-019 in the other direction: a defect found in one
place and left in its twin.

It only surfaced because the guard above made the malformed render impossible.
Until then the LTV test asserted `getByRole("alert")` **exists**, which the
subject-less warning satisfied perfectly — so a test named "shows the unresolved
alert" was passing on an alert that said nothing. It now asserts the content.

That is the hand-off's own "an assertion about the visible half says nothing
about the half that acts", turned once more: asserting that an element EXISTS
says nothing about whether it says anything.

A scan across every `open_in_scope_count` / `breakdown` pair in the suite found
no others.

### The remainder lesson: no residual left in the breakdown

Checked, since the hand-off asked and noted it had found none last time either.
There is none, and the reason is structural rather than lucky: the classifier is
three POSITIVE tests (`evaluation_outcome is not None`, `origin is
DETERMINISTIC_RULE`, `origin is AI_CROSS_SOURCE`) with `other` as a genuine
`else`. None of the three is a fallback, so `other` can actually fire — an
explicit `other` under an else-branch classifier would have been the same defect
wearing the fix's label. `UnresolvedAlert` renders it, so it is visible as well
as counted.

Two remainders elsewhere in the tree are fine and were left: `findings-list.tsx`
computes `hiddenOpen` and `filteredOut` by subtraction, but each subtracts a
strict subset from its superset, so the label cannot be wrong about what is
missing. The rail's `unrecognised` is the same shape, deliberately.

### Confirmed, not changed

- **Extracting `UnresolvedAlert` from three byte-identical copies.** Right, and
  the evidence is the bug that prompted it: fixing one copy left the DTI panel
  reading "91" on the same screen. Three surfaces that must agree are not three
  surfaces with a reason to diverge — and if one ever earns a different alert, a
  prop is the cheaper change than three copies that drifted silently for months.
- **Threading override attribution through three backend services.** The models
  already recorded `actor_user_id` and `note`; all three services dropped them on
  the way out. That is one defect in three places, not three tickets, and one
  shared helper is the right size. A frontend ticket that needs "who set it" and
  finds the backend discarding it should thread it, not stub it.
- **Leaving the 3 cross-source findings listed nowhere.** Correct. Where that
  family belongs is a product decision, and inventing a tab for it inside a UI
  ticket would be the worse error.
- **The fixture-coherence conclusion.** Right, and worth stating as the rule it
  is: a fixture that type-checks can still describe a state the system cannot
  produce, and a test built on one passes while testing nothing. `tsc` proves the
  shape, not the coherence.

### Raised to the user, not filed

The hand-off asks that A22's product question go to the user rather than stay in
AMENDMENTS, and that is right. Two of the three unaccounted findings come from
`xsrc.income.employer_name_consistency` — the rule LP-606 retired, and the same
rule the LP-UI-018 review caught the ledger deferring to. It has now surfaced
twice in four tickets from opposite directions: once as a verdict being rendered,
once as a count with nowhere to render.

Those findings are open, counted, and unresolvable — the alert tells a processor
they can be "applied or overridden" and no screen offers either. That is not a UI
defect to fix here; it is the retirement being half-done, and every remaining
ticket in Epics C–G is another chance to bind to the wrong generation.

Surfaced to the user with this review.

### Verification

Frontend `tsc` and `biome` clean over 235 files, **678 tests** (from 674), build
compiles into `.next-review` with the dev server left running. Backend `ruff` and
`mypy` clean over 449 files, **6,013 pass** with the two known `.env` failures.

| mutation | result |
| --- | --- |
| drop the empty-parts guard | 1 test fails |
| fold `other` into `governed` | 1 test fails |
