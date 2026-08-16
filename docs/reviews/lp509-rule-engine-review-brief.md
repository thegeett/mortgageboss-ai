# Review brief — the LP-509 rule-engine correction (LP-509, LP-510, LP-511)

**For a reviewer.** This is one body of work across three commits, driven by one real loan file
(LF-WCHG). It changes rule specs, a parser, a DB schema, the at-rest PII guard and the deploy script.
Read the "where to push hardest" section before the change list — the risk is not evenly spread.

## Commits

| SHA | What |
|---|---|
| `959f0e8` | The nine LP-509 fixes |
| `61c663a` | Correct LP-509's A1 count from 104 to the measured 94 |
| `de4c210` | LP-510 (MISMO backfill) + LP-511 (IN-3 regression) |

## The problem it started from

LF-WCHG produced **162 findings — 132 "Needs attention", 30 "Satisfied"** — of which roughly 13 were
genuine. A processor facing 132 items where ~10% are real learns to ignore the output.

## Measured result

| | before | after deploy | after LP-510 backfill (projected) |
|---|---|---|---|
| Needs attention | **132** | **34** | **~30** |
| Satisfied | 30 | 34 | 34 |
| No longer applies | 0 | 97 | ~101 |

**A 74% reduction, measured, not projected** — the 34 is from a read-only query against staging after
the deploy, not arithmetic.

## What changed, and what each was worth

| | Fix | Measured effect |
|---|---|---|
| A1 | AS-2/AS-12 gained the `txn.is_money_in` predicate AS-1 always had. `per_deposit` enumerates one subject per TRANSACTION, so both rules were asking "where did this deposit come from?" of ATM fees and utility bills. | **94 findings retired** |
| A2 | ID-6 required MISMO keys (`borrower.1.name`, `property.address`) that nothing emits — it fired on **every loan file in the system**. | ID-6 → satisfied |
| E1 | New static guard: every MISMO fact key a consumer reads must be one the emitter can produce. | catches A2's class |
| C1 | The at-rest PII guard now names the offending path (never the value). That found a real defect: a uuid4 whose final 12-hex group is all decimal (1 in 281) read as an account number, and `loan_file_id` is STABLE — so ~1–2% of loan files could never persist a snapshot, on any run, permanently. | a whole failure mode removed |
| A4 | Bureau abbreviations expanded on both sides of the lender-name compare (`UNITED WHSLE MORT` ↔ `United Wholesale Mortgage, LLC`). | RE-1 → satisfied; DT-6 now reports a REAL payment discrepancy instead of abstaining |
| A5 | PC-2/PC-3/PC-7 scoped purchase-only on `loan.purpose`. | 3 retired |
| B1 | `PropertyInProjectIndicator` / `PUDIndicator` captured through parser → model → snapshot; `property.type` derived from them. | 4 (pending LP-510) |
| A3 | IN-3's three arithmetic errors: cumulative YTD summed across stubs, per-document documented monthly summed across documents, whole-month divisor. | 62.6% "shortfall" → negative |
| D1 | New rule **IH-9** (hazard policy expired). | surfaced a 13-month-lapsed policy nothing had reported |

## Where to push hardest

1. **`deterministic._reason_fields` (LP-511)** — adds a `{name}_percent` companion for every Decimal
   operand, and `specs.py` now strips the suffix before validating placeholders. Shared by every rule.
   Check the validator still rejects a genuinely unknown `{foo_percent}`.
2. **The at-rest PII guard rewrite (C1)** — it is the last line of defence before raw PII is stored. It
   changed from a regex over serialized text to a structural walk, and it now SKIPS canonical uuids.
   Verify the skip cannot hide a real leak (a 36-char uuid is not an SSN shape), and that the error
   never prints a value.
3. **`_property_type` (B1)** — decides a mortgage property classification. The load-bearing judgement is
   that `in_project == false` rules out a condo while `AttachmentType == Detached` does NOT (Fannie
   recognises detached condominiums). Every undecidable branch must abstain, not default.
4. **The A4 abbreviation table** — a wrong expansion produces a false `satisfied`, which nobody re-reads.
   It is a fixed table rather than a distance function for exactly that reason. Check for an entry that
   could equate two different lenders.
5. **`backfill_mismo_property_indicators.py` (LP-510)** — writes to production data. Check: report-only
   by default, only ever fills a NULL, one unreadable file cannot stop the batch.
6. **Migration `c3e940f8ee9d`** — adds two nullable columns and rebuilds `readonly.properties`. The
   downgrade reads C7's view text rather than copying it; confirm that is sound.

## Known open issues — written up, not fixed

| Ticket | Severity | Summary |
|---|---|---|
| **LP-513** | **HIGH** | **No `per_borrower` rule produces a finding on a real file** — IN-1, IN-12..IN-16, ID-5, CR-4, CR-10 all silently inert. Nine live rules, no error, no log line. |
| LP-512 | medium | A rule that changes `subject_enumeration` orphans its old findings — they persist showing stale values. |
| LP-514 | medium | An insurance renewal beside the policy it replaces makes IH-3/IH-9 abstain, so supplying the CORRECT current policy made the file report LESS. |

## Corrections made during the work — worth checking the reasoning held

- **The ticket's "104" was wrong**; the measured figure is **94** (2 × 47). The original arithmetic
  (2 rules × 47 transactions = 104) does not multiply, and the claim was impossible anyway: gating those
  rules can move at most 94 subjects to `not_applicable`.
- **B2 was already done** — `loan.purpose` has been a tag since LP-424, which declared it for this
  purpose and deferred only the wiring.
- **A `content_id` hypothesis was raised and withdrawn** — content ids are letter-prefixed, so a digit
  run inside one is never `\b`-bounded. The exemption built on it was removed.
- **B1 was verified locally by importing the MISMO fresh**, which silently created the one condition
  staging cannot have. That is what LP-510 exists to fix.

## Not verified

- The LP-510 backfill has not been run against staging.
- LP-511's revert has not been re-deployed; IN-3's finding is still the stale orphaned row.
- `tests/verification/snapshot/test_persistence.py` has a pre-existing random-order flake (passes in
  isolation and with `-p no:randomly`; failed ~2 in 15 full runs). Not caused by this work, not fixed.

## Suite

4943 passed, 5 skipped, 1 xfailed. ruff and mypy clean.
