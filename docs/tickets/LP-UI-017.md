# LP-UI-017 — Reconciliation read model (backend)

- **Ticket:** LP-UI-017 — the one new read model this redesign needs
- **Epic:** Ledger redesign → Epic C (Core screens)
- **Status:** Completed
- **Date:** 2026-08-30
- **Blocks:** LP-UI-018 (the reconciliation ledger UI)
- **ADR:** **ADR-391** — what counts as agreement

## Summary

`GET /loan-files/{id}/reconciliation` returns, for one file, every field that has
a stated value (1003/MISMO), a found value (extraction), or both — with per-row
agreement and the provenance behind the found side. Deterministic; no AI in this
path.

Against the MISMO seed file, real output:

| agreement | field | stated | found | provenance |
|---|---|---|---|---|
| differs | Base monthly income | 28,168.80 | 18,697.06 | `Akash W2 BofA 2025.pdf` p.1 |
| differs | Employer | Bank of America | Wells Fargo Bank, N. A. | `Akash W2 BofA 2025.pdf` p.1 |
| differs | Checking balance | 326,477.91 | 10,120.34 | `BofA checking April.pdf` p.1 |
| missing | Appraised value | 1,450,000.00 | — | *no appraisal extracted* |
| missing | Homeowner's insurance | — | — | *not stated, no declaration received* |

and on a second file, `not_stated` for an insurance declaration that exists in a
document but never on the application — the disclosure direction, working.

## What Changed

- `app/services/reconciliation.py` (new) — `Agreement`, `RowSource`,
  `ReconciliationRow`, `reconcile_loan_file()`, and the three comparison rules.
- `app/api/loan_files.py` — the endpoint, behind the same `get_loan_file`
  tenant gate every other file route uses.
- `tests/services/test_reconciliation.py` (new) — 16 tests, all mutation-checked.
- `decisions.md` — **ADR-391**.

## Two defects I introduced, found by checking rather than by review

Both are the same class the last three reviews have caught — deriving something
the codebase already decides — and both looked right in the output.

**1. The income row compared a monthly figure to a pay-period one.** The first
version read a pay stub's `gross_pay` and put it beside the stated monthly total:
$28,168.80 against $8,076.93, marked **differs**. That is not a disagreement, it
is a unit error, and the codebase already forbids it — **ADR-328**: "an assumed
[frequency] is a silent 12x miscalculation", and the tag layer is closed to
unknown frequency for exactly this reason.

The found side now prefers a W-2's annual wages ÷ 12, which assumes nothing.
Where only a pay-period figure exists the row keeps its provenance, reports
`missing`, and says why — refusing to guess rather than producing a confident
wrong answer.

**2. Employer matching produced false disagreements, and my comment claimed it
did not.** I wrote that reusing `normalize_name` meant "Cascade Robotics Inc."
and "Cascade Robotics" were the same employer. Measured, they are not:
`normalize_name` is a **person**-name normaliser and does not strip legal forms.
On real seed data it reported `Ambio, Inc.` vs `Ambio, DBA Ambio, Inc` as
**differs**.

Legal-form tokens are now dropped and the smaller token set must be contained in
the larger. `Ambio, Inc.` ≡ `Ambio, DBA Ambio, Inc`; `Cascade Robotics Inc.` ≡
`Cascade Robotics`; **`Bank of America` still ≠ `Wells Fargo`**, which is the
seed file's real finding and had to survive the fix.

## Verification

**16 tests, four mutations, all caught:**

| mutation | test that failed |
|---|---|
| income boundary `<=` → `<` (disagreeing with the engine's `LE`) | exactly ten percent still matches |
| stop stripping company suffixes | the same employer spelled differently matches |
| give money a $1 tolerance | a single cent differs |
| collapse `not_stated` into `missing` | direction is preserved |

**Against the seed data**, both MISMO-imported files, through the real endpoint
with a real token — the table above.

**CI.** ruff, mypy clean over 449 files; full suite **5,980 pass** (from 5,964)
with the two known `.env` failures.

## Findings raised

1. **Coverage is five rows, and the ticket's minimum is five categories.** Income,
   employer, assets, valuation and the insurance gap are covered. What is *not*
   covered, and would be the obvious next additions: liabilities (the engine
   already has `stated_liabilities` and `credit_report_liabilities` as
   `ObligationRef` sets, so this is a set-difference row rather than a field row),
   and the subject-property address. Both need a row shape this model does not
   have — one stated thing against *many* found things — and inventing that shape
   speculatively seemed worse than shipping the field rows and saying so.

2. **The ledger can drift from the findings on employer names.** Income cannot,
   because both read `_VARIANCE_10`. Employer matching exists only here, so if the
   engine ever grows an employer check it must import this rule rather than write
   a second. Recorded in ADR-391's *Consequences*.

3. **Exact-cents money comparison will look noisy the first time a lender's
   export rounds to the dollar.** That is a real disagreement to see rather than
   hide, but it is a deliberate choice someone should be able to find, which is
   why it is in the ADR rather than only in the code.

## Assumptions and decisions

- **Assumed** the found value for a field key may appear in several documents
  (two pay stubs both report `gross_pay`), so `_found_fields` returns a list per
  key and each row states its own preference order between synonyms.
- **Decided** the insurance row exists even when both sides are empty. Its
  absence *is* the finding; a ledger that only listed fields it had data for
  would omit exactly the row a processor must act on.
- **Decided** tenant scoping is the endpoint's, through the existing
  `get_loan_file(db, company_id=…)` gate, rather than a second check inside the
  service — one gate, the same one as every other file route.

## Files

- `app/services/reconciliation.py` (new), `app/api/loan_files.py`,
  `tests/services/test_reconciliation.py` (new), `decisions.md` (ADR-391)
