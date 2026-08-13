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
| **IH-7** | **$1,000,000 per occurrence** | minimum condo-project general liability | Fannie Mae Selling Guide **B7-4-01**, *General Liability Insurance Requirements for Project Developments* | 08/05/2026 |
| **IH-7** | **100% replacement cost** | required master property coverage basis | Fannie Mae Selling Guide **B7-3-03**, *Master Property Insurance Requirements for Project Developments* | 08/05/2026 |
| IH-2 | *none* | a name compare; the matching tolerance (2-token prefix) is not a domain number | — | — |
| **MI-1** | **LTV > 80%** | conventional MI requirement | Fannie Mae Selling Guide **B7-1-01**, *Provision of Mortgage Insurance* | ⚠️ **NOT OBTAINED — tier S** |
| **MI-4** | **1.75% (175 bps)** of base loan amount | FHA upfront MIP | HUD **Mortgagee Letter 2023-05** | **2023-02-22** (tier P) |

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

---

## 5. From LP-486 (CR-12 disputed accounts)

**Confirm the dispute vocabulary is complete.** CR-12 recognises exactly these and **abstains on anything
else** (ADR-376) — it never infers from unfamiliar bureau text:

*Means disputed:* `Y` · `yes` · `account disputed by consumer` · `consumer disputes this account` ·
`dispute in progress` · `account information disputed by consumer` · `consumer disputes account information`

*Account-status remarks, NOT disputes:* `N` · `no` · `ACCOUNT IN FORBEARANCE` ·
`ACCOUNT CLOSED BY CREDIT GRANTOR` · `PAID ACCOUNT` · `TRANSFERRED` · `ACCOUNT CLOSED` · `DEFERRED`

⚠️ **One real value abstains today and we want your call on it:** LF-96SV carries
`ACCOUNT PREVIOUSLY IN DISPUTE-NOW RESOLVED-REPORTED BY SUBSCRIBER`. We deliberately do **not** read that as
"not disputed" — that would be inferring a resolution the bureau did not state. **Should a
resolved-dispute remark be treated as no dispute, or stay a review item?**

**The FHA disputed-derogatory branch is NOT built.** FHA sets separate thresholds for disputed derogatory
accounts and has a manual-downgrade path with aggregate-dollar tests. `loan.agency` does not exist as a fact
and `LoanProgram` is a two-value enum, so the rule builds the **detection only**, which is
agency-independent. **What are the FHA thresholds, and should a disputed derogatory account route
differently?**

## 6. From LP-486 (CR-3 paid-to-qualify) — a missing input, not a missing threshold

**CR-3 could not be built, and the blocker is an input nobody supplies.** Its trigger is
`liab.excluded_paid_off` — *"marked paid-off/excluded to qualify"*. That is an **underwriting claim**, not a
bureau fact: the credit report's 14 tradeline fields state balances and statuses, never "this debt is being
excluded to qualify", and MISMO's liability projection carries only four fields (type, monthly payment,
unpaid balance, holder name). **Where does the claim that a debt is paid off to qualify come from — the
1003, a processor entry, or somewhere else?** Until it has a source, CR-3 has no trigger and would
`couldnt_check` on every file forever.

The researched rules for CR-3 are recorded and ready for when the trigger exists:

| point | value | source |
|---|---|---|
| A revolving account paid to $0 **need not be closed** to exclude the payment from DTI | — | Fannie Selling Guide **B3-6-07**, *Debts Paid Off At or Prior to Closing* |
| An installment loan with **≤ 10 remaining monthly payments** may generally be excluded even if not paid off | 10 | Fannie Selling Guide **B3-6-05**, *Monthly Debt Obligations* |

⚠️ **Neither page was fetched in this ticket** — they are carried from the ticket brief and are marked
**STARTER** until read from the live guide with its page date, per ADR-361.

**The evidence hierarchy (your ruling), for when it is built:** creditor payoff/zero-balance statement →
creditor transaction history showing $0 → bank statement or transaction record showing the payoff → Closing
Disclosure when paid through closing. ⚠️ **A screenshot supports the file but is not equivalent to a creditor
statement** when qualification depends on it.

**Source of funds** — Freddie requires the funds used to pay down debt for qualification to be documented.
Noted as a requirement; **not built** (it needs asset-side inputs outside this cohort).

**Reconciliation** — a credit report still showing a balance does **not** defeat newer creditor evidence; the
newer evidence wins and the discrepancy is surfaced.

## 7. `liab.account_type` — the mapping that keeps it unwired

Unchanged from LP-483 and still blocking: the declared enum is
`revolving | installment | mortgage | heloc | open_30 | collection | lease | student | other`; the sources
emit **`REV` / `AUTO` / `MTG` / `INST` / `OPEN`** (credit report) and
**`MortgageLoan` / `Installment` / `Revolving`** (MISMO). **Which raw code maps to which enum value, and
should an unmappable code abstain?** ADR-376's closed-vocabulary pattern is the shape to use once the
mapping is confirmed.

---

## 8. From LP-508 (the distrusted-field guard) — one question for you

**IH-1 is currently suspended, not merely degraded.** Its only gated input —the homeowners binder's
loss-settlement basis — is on the distrusted-field list (doc 104 read "coinsurance contract" off a
replacement-cost HO3, and IH-1 ships `auto` with no confidence defence). Because the guard keys on the
**field**, every binder now returns `needs_review` awaiting a processor's confirmation: **replacement-cost
and actual-cash-value alike, on 100% of files**, not just the wrong ones.

**Question: is a distrusted field the right thing to block a verdict on, or should it annotate one?** Today
it blocks — the finding reaches the processor marked "confirm this value" rather than asserting an
insurance-adequacy answer. The alternative is to let the rule assert and attach a caution. We chose blocking
because an auto-asserted verdict off a known-wrong field is the harm; you may weigh a processor's time
differently.

**Related: when should an entry be removed?** The list is meant to shrink. Each entry names the document and
the error so it can be deleted once the extractor is fixed — but "fixed" needs a bar. Is one clean re-read of
the failing document enough, or do you want a sample?

⚠️ **What this does NOT cover, for the record:** doc 253's gift read as $224,307.94 instead of $24,307.94.
A lone amount with no sibling to contradict it is invisible to both this layer and LP-474's consistency
checks. Catching it needs a comparison against the source document — a layer that does not exist yet.

---

## 9. From LP-487 (insurance: IH-2 mortgagee clause · IH-7 condo master policy)

### 9a. ⚠️ IH-2 cannot fail a file — confirm that is what you want

A mortgagee clause that does **not** match the lender on the Closing Disclosure returns **`needs_review`
("confirm"), never `fired`.** The reason is in your territory rather than ours: the one file in our corpus
that carries both documents reads **"Sistar Mortgage Company"** on the CD and **"United Wholesale
Mortgage"** in the clause. Our understanding is that in broker and correspondent deals the CD names the
creditor while the clause names the investor who will hold the loan, so the two legitimately differ.

**Questions.** (1) Is that reading right? (2) **How often is a genuine mismatch a real defect** rather than
this pattern? If it is usually a real defect, we have the direction wrong and IH-2 should fire. (3) Is there
a signal on the file that distinguishes the two — a correspondent/wholesale indicator we could read — which
would let us fire on the true mismatch and stay quiet on the legitimate one?

### 9b. IH-2's matching tolerance — two tokens

Two names agree when their token lists match or one is a token-prefix of the other covering **at least two
tokens**, after stripping ISAOA/ATIMA, "c/o", corporate suffixes and punctuation. This absorbs the real
corpus variance (`"United Wholesale Mortgage, LLC ISAOA"` vs `"United Wholesale Mortgage, LLC"`).

⚠️ **The known false-satisfied direction, stated rather than discovered later:** a CD naming "First
National" against a clause naming "First National Bank of Chicago" would **agree** under this rule, and
`satisfied` is the one verdict no human re-reads. Is two tokens enough tolerance, or should a prefix match
below full equality route to `needs_review` as well?

### 9c. ⚠️ IH-7 does NOT check fidelity/crime coverage — a deliberate omission

Fannie **B7-4-02** requires fidelity/crime coverage for projects above a unit-count threshold. We did not
build it: the unit count lives on the condo questionnaire (`total_units`), which is **empty on the one
questionnaire in our corpus**, and the master policy document carries `fidelity_crime_coverage_present` but
no unit count. Building on an input that never resolves would have made IH-7 permanently `couldnt_check`
and hidden the two checks that DO resolve.

**Questions.** (1) Confirm the unit-count threshold you want us to use. (2) Is the questionnaire the right
source, or is there a document that reliably carries the unit count? (3) Until then, is presence +
replacement-cost basis + liability limit an acceptable IH-7?

### 9d. IH-7's coverage-basis reading is a leading-phrase match, not an exact one

The master policy's basis field is **prose, not a code**. The four real policies in our corpus read
`"Guaranteed Replacement Cost"`, `"Replacement Cost"`, `"REPLACEMENT COST AT AGREED VALUE WITH NO
CO-INSURANCE"` and `"Replacement Cost (RCV) at Agreed Value with no coinsurance; 100% replacement cost for
portion of building insured by Association"`. An exact vocabulary match would abstain on three of the four.

So we match the **leading phrase** and treat what follows as elaboration. Two protections are kept: an
unrecognised phrase abstains (never "inadequate"), and a value naming **both** replacement cost and actual
cash value abstains whichever leads — a mixed basis ("ACV roof, replacement cost dwelling") is your call,
not ours. **Is treating the leading phrase as the policy's basis correct**, or can a policy state its real
basis in a trailing qualifier we would then miss?

---

## 10. From LP-488 (MI-1 · MI-4 · CO-1 · AU-3; RE-2 dropped)

### 10a. ⚠️ MI-1's 80% — the page date was NOT obtained

The value is Fannie Mae Selling Guide **B7-1-01**, and the 80% figure is universally reported — but **we
did not read the page this pass**, so it is recorded as **tier S**, not tier P. Per ADR-361 a value is
cited or it is marked unobtained; it is never recalled and dressed as read. **Please confirm the figure
and the current page date**, or point us at your investor overlay if it is stricter.

### 10b. ⚠️ MI-1 cannot confirm that MI is PRESENT — an input gap, not a design choice

MI-1 computes the LTV and reports "MI is required — confirm the file carries it" (`needs_review`). It
**never fires**, because nothing in the system can see whether mortgage insurance exists:

- **No document type carries an MI certificate or an MI factor.** The only mortgage-insurance field in
  all 121 schema specs is `form_1098.mortgage_insurance_premiums` — a *prior-year* figure for an
  *existing* mortgage.
- `mi.certificate_present` is an AI tag with no calibration, so it cannot gate a live rule.
- `housing.mi_monthly` is undeclared and reaches nothing.

**Question: is an MI certificate a document we should be extracting?** If your files carry one, adding a
schema spec for it would turn MI-1 from an advisory into a real presence check (and would unblock MI-2,
MI-3 and MI-5 as well).

### 10c. ⚠️ MI-4's annual MIP is NOT evaluated, and its rate matrix was deliberately not written down

MI-4 checks the **upfront** premium only — (note amount − base loan amount) against 1.75%. The **annual**
premium is not checked because **no document carries a monthly MIP figure for this loan**. ML 2023-05's
per-cell annual matrix (by LTV × term × base loan amount, reported as a 0.15%–0.75% range) was **not
obtained**, so **no cell from it is written anywhere in the codebase** — a test enforces that, so nobody
later builds against a number we never read.

**Questions.** (1) Do you want the annual MIP checked at all, and against what document? (2) If yes, we
need the matrix from ML 2023-05 itself, cell by cell.

### 10d. ⚠️ Two FHA exemptions we cannot detect

ML 2023-05: **Section 248** mortgages (Indian Lands) require **no upfront MIP**; **Section 247**
(Hawaiian Home Lands) require **no annual MIP**. No field in the system identifies either. A loan
financing no upfront premium therefore lands on `needs_review` — "confirm it was paid in cash or that
this loan is exempt" — rather than failing. **Is that the right landing place**, and do your files carry
anything that would identify a Section 247/248 loan?

### 10e. ⚠️ CO-1 is presence only — warrantability is still unbuildable

Your standing point is that condo rules must distinguish **warrantable from non-warrantable**, not merely
confirm a questionnaire exists. CO-1 does the latter, deliberately: **`property.is_warrantable_condo` has
no source field in any of the 121 schema specs**, because warrantability is a project-review *conclusion*
(Form 1076 / PERS), not a readable datum. It is left inert and a test keeps it that way.

**Question: how is warrantability actually determined on your files** — a lender project-review sheet, a
PERS approval letter, or a judgment a processor makes from the questionnaire's contents? The answer
decides whether CO-3/CO-5 are extraction work or a genuine judgment rule.

### 10f. ⚠️ AU-3 is calibrated on ONE document — is it worth shipping?

There is exactly **one `aus_findings` document across 303**, and it is an **LPA** reading `ACCEPT` /
`ELIGIBLE`. That single file is genuinely valuable — it proved the DU-shaped catalog vocabulary would
have misread every Freddie file — but it means:

- the **DU spellings are researched, not observed**: `Approve/Eligible`, `Approve/Ineligible`, `Refer
  with Caution`. No DU file has ever exercised them.
- the **DU ↔ LPA equivalence is our domain claim**: DU splits recommendation from eligibility, LPA gives
  a risk class plus eligibility. We treat LPA `Accept` as DU `Approve`. Standard industry equivalence —
  but a mapping, not a reading.

**Questions.** (1) Confirm the equivalence. (2) Are there engine wordings we are missing (LPA
`Caution`, `Refer/Eligible`, `Out of Scope` variants)? (3) **Would you rather AU-3 waited for more AUS
documents?** It abstains on anything unrecognised, so the failure mode is silence, not a wrong answer —
but that is our call to check with you.

### 10g. RE-2 was dropped — retained-property data does not exist

RE-2 (*retained property → tax/insurance docs present*) is **not buildable and was not built hollow**:

- **No REO or retained-property concept exists anywhere** — nothing in the MISMO section (21 facts, none
  about another property) and nothing in the data model.
- The non-subject property document types exist (`property_tax_bill_non_subject`,
  `property_profile_non_subject`, `other_property_note`) but are **0 of 303** in the corpus.
- Decisively: **nothing states that a borrower RETAINS a property.** Owning another property is not the
  same as keeping it — the borrower may be selling it — and that trigger is the rule's whole premise.

**Question: where does retained-property information live on your files today?** If it is the 1003's REO
section, that is an import gap we can close; if it is something a processor knows and records manually,
RE-2 needs a different shape entirely.

---

## 11. From LP-490 (credit AI: CR-1 · CR-4 · CR-5 · CR-6 · CR-8 · CR-10)

⚠️ **All six are built INERT.** They read AI tags with no measured accuracy, so none is live. What
follows is what we could not settle without you.

### 11a. ⚠️ The Chapter 13 split is not expressible — and we chose the conservative side

Your matrix distinguishes a **discharged** Chapter 13 (2 years) from a **dismissed** one (4 years), and
Chapter 7/11 at 4 years. `liab.derogatory_type` has **one** `bankruptcy` value; nothing on the report
distinguishes chapter, or discharge from dismissal. Applying the shorter 2-year period to an
undifferentiated bankruptcy would clear a Chapter 7 **two years early**, so **CR-6 applies 4 years to
every bankruptcy**. A discharged Chapter 13 will therefore be surfaced for review between years 2 and 4
rather than cleared.

**Question: is that the right trade?** The alternative is to extract chapter and disposition (the
`bankruptcy_discharge` document carries `bankruptcy_chapter`, `discharge_order_date` and
`case_status_after_discharge`, so it is buildable) — but only when that document is in the file.

### 11b. ⚠️ Foreclosure, short sale and deed-in-lieu have no completion date

You were explicit that seasoning must run from the **actual event date**, never the report date, and
CR-6 abstains rather than substituting. But `public_records[]` carries `discharge_or_satisfied_date`
only — a **bankruptcy** has a real date; a **foreclosure, short sale or deed-in-lieu** usually appears
as a tradeline *status* with no completion date anywhere.

**Question: where does the completion date live on your files?** The deed, the title commitment, an LOE?
Until then those three rows of the matrix will `couldnt_check` far more often than they resolve.

### 11c. Ordinary consumer lates — a separate track we did NOT build

Your guidance (last 12 months high attention · 13–24 months still relevant · beyond 24 months context ·
weighed with severity, frequency and re-established credit) is a **judgment**, not a waiting period.
Folding it into CR-6's matrix would apply a four-year bar to a single 30-day late, so we left it out.

**Question: does this want its own rule?** If so, is it per-tradeline or a whole-profile judgment?

### 11d. ⚠️ A mortgage charge-off — CR-6 or CR-10?

We put it in **CR-6** (a 4-year seasoning requirement) and kept it out of CR-10's dollar logic, on your
note that a mortgage charge-off is not an ordinary collection. But `liab.derogatory_type` has one
`charge_off` value and does not say whether the account was a mortgage. **Confirm the split**, and
whether a *consumer* charge-off should be seasoned at all or only counted in the collection aggregate.

### 11e. Rental history

You ruled rental history is **not** equivalent to mortgage delinquency codes and must not be mapped onto
them, so CR-8 evaluates mortgages only. **Is rental history in scope at all?** If so it needs its own
rule and its own source document.

### 11f. ⚠️ CR-8 cannot compute "current at application"

Your ruling records Fannie's definition — an existing mortgage is current when **no more than 45 days**
have elapsed since the last paid installment date. **No last-paid-installment date is extracted**, so
CR-8 records the definition but cannot apply it. **Is that date on your credit reports?**

### 11g. ⚠️ CR-10 abstains on manually underwritten files

The **DU-vs-manual axis does not exist as a fact** on any file, and we did not invent one. So a manually
underwritten loan returns `manual_underwriting_not_supported` rather than a guessed branch — the
thresholds differ ($250/$1,000 regardless of occupancy vs the DU occupancy matrix), so guessing could
clear a collection that must be paid.

**Question: how do you know which path a file is on?** If it is on the AUS findings, we can read it —
AU-3 already extracts the recommendation.

### 11h. `liab.account_type` — the vocabulary mapping, still unwired

Its enum is `revolving / installment / mortgage / heloc / …`; the sources emit `REV` / `AUTO` / `MTG` /
`INST` and `MortgageLoan` / `Installment`. A **parsed** tag is not validated against `allowed_values`,
so declaring it would ship out-of-domain values silently. It stays unwired, and CR-8's need is met by a
derived `liab.is_mortgage` with an abstain. **Please confirm the mapping** and we will wire it properly.

### 11i. ⚠️ Are CR-1 and the deposit-obligation check one finding or two?

CR-1 flags a debt on the credit report that the application omits. FR-4/FR-5's
`txn.implies_obligation` flags a bank-statement transaction implying a debt nobody stated. **Same
underwriting condition from two directions.** Should a processor see one finding or two? Two risks
double-reporting the same debt; one risks hiding that the evidence came from two independent places.

### 11j. What the corpus does and does not establish

**Three credit reports.** One inquiry row (CR-5). **Zero** public-record rows and no derogatory events
(CR-6). **Zero** collection or charge-off codes (CR-10). `payment_history_24mo` 0–84 chars across 17
formats; `worst_delinquency` 2/35 in two incompatible formats (CR-8).

So: CR-1 has **one** file supporting a bounded negative, and **CR-5, CR-6 and CR-10 have never been
observed firing on real data at all.** Calibrating any of them needs real files, not fixtures — a
self-authored derogatory event or collection leaks its own answer (ADR-332, and the LP-487 amendment on
self-authored labels).
