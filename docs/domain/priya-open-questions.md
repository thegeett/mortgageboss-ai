# Priya — open questions and self-set thresholds

**A REVIEW LIST, NOT A BLOCKER LIST.** From 2026-08-12 the engine is built on thresholds we research and
cite ourselves. Every number below is **live and in force now**; each is recorded here with its source so she
can confirm or revise it. Nothing waits on her to be built.

⚠️ **ADR-361 still holds: no threshold is ever recalled from memory.** Every value carries a publisher,
section and page date, fetched from the live guide.

---

## 1. Thresholds we set ourselves — for confirmation

| rule | value | what it governs | source | page date |
|---|---|---|---|---|
| **CR-13** | **4 calendar months** | max credit-document age on the note date | Fannie Mae Selling Guide **B1-1-03**, *Allowable Age of Credit Documents and Federal Income Tax Returns* | 04/02/2025 |
| **PR-6** | **12 calendar months** | max appraisal age (beyond → **new appraisal**) | Fannie Mae Selling Guide **B4-1.2-04**, *Appraisal Age and Use Requirements* | 06/04/2025 |
| **PR-6** | **4 calendar months** | beyond → an **appraisal update** (Form 1004D) is required | same as above | 06/04/2025 |
| CL-1 | *none* | a date ordering (lock expiry vs closing); `zero` is a comparison boundary, not a domain number | — | — |

**Questions on these three:**

1. **CR-13 — is four months right for our lenders?** The guide says four months for *all* mortgage loans.
   Some investors are stricter (90 days is common). Should we hold the agency number or an overlay?
2. **PR-6 — do we want the middle band to reach the processor as a condition?** Today an appraisal aged
   5–12 months returns `needs_review` with "an update (Form 1004D) is required" — deliberately **not** a
   failure, because the appraisal is usable with the update. Confirm that is how you want it surfaced.
3. **PR-6 — the desktop-appraisal band is NOT implemented.** B4-1.2-04 caps a **desktop** appraisal at four
   months (a *new* appraisal, not an update). We have no tag distinguishing desktop from traditional — the
   extractor's `form_type` would need a classification ruling (the ADR-353 open-vocabulary class). **Today a
   desktop appraisal aged 5 months reports "update required" where the guide requires a new appraisal.**
   Two questions: is that gap acceptable short-term, and what `form_type` values mean "desktop"?

---

## 2. ⚠️ Note date vs closing date — a substitution we made

Both CR-13 and PR-6 are written by the guideline against the **note date**. The snapshot carries only
`contract.closing_date`, so **that is what both rules compare against**. Usually the same day; not always.

**Question:** is closing-date-as-note-date acceptable, or do we need to capture the note date separately? A
file that closes and notes on different days would age its documents by our number, not the guide's.

---

## 3. DT-4 — a rule we cannot build, and the missing datum

**DT-4 (Property taxes estimate) is not buildable and has been dropped.** Not deferred — there is nothing
to build it from.

There is exactly **one** property-tax source in the entire system: `housing.taxes_monthly`, derived from
`property_tax_bill.annual_tax_amount ÷ 12` — the same field the DTI reads directly. MISMO carries **no**
property-tax field at all. So both operands of "tax used vs assessed" trace to one extracted field on one
document, and the compare can never fire (ADR-330 vacuity).

The alternative reading — assessed value × a **millage rate** — needs a millage rate that exists in no
field, no tag, and no MISMO key.

**Question:** where should a millage rate (or an independently-stated escrow tax figure) come from? Until
one exists, DT-4 has no second operand and cannot be written.

⚠️ **Note for the record:** DT-4 was LP-476's single **"WRITABLE-NOW"** rule. It is not writable. Anyone
reading that census will otherwise start here again.

---

## 4. Standing items from earlier tickets

- **Credit vocabulary (ADR-353).** `liab.account_type`'s declared enum is
  `revolving | installment | mortgage | heloc | open_30 | collection | lease | student | other`; the sources
  emit `REV / AUTO / MTG / INST / OPEN` (credit report) and `MortgageLoan / Installment / Revolving` (MISMO).
  **Which raw code maps to which enum value, and should an unmappable code abstain?** Until this is answered
  `liab.account_type` has no parsed producer.
- **Dispute interpretation (CR-12).** `is_disputed` is a clean `Y`/`N` on one bureau's reports and free text
  (including non-disputes) on another. **Is a non-empty dispute field a dispute?**
- **Undisclosed liability (CR-1 / CR-4).** The per-liability matcher's bar: a false **match** hides a real
  undisclosed debt; a false **non-match** fabricates one on a clean file. **Both fail expensively** — the bar
  is a trade, not a lean.
- **The agency axis.** `LoanProgram` has only `CONVENTIONAL` and `FHA`. CR-9's 1% vs 0.5% is
  Fannie-vs-Freddie *inside* conventional and is not expressible. **Do we need an agency dimension?**
