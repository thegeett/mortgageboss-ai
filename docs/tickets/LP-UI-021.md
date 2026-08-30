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
