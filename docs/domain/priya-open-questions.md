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
| **MI-1** | **LTV > 80%** | conventional MI requirement | Fannie Mae Selling Guide **B7-1-01**, *Provision of Mortgage Insurance* | **04/02/2025** (tier P) |
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

### 10a. ✅ MI-1's 80% — page date now obtained (was tier S)

**Resolved 2026-08-13.** The page was fetched and the value confirmed verbatim: Fannie Mae Selling Guide
**B7-1-01**, *Provision of Mortgage Insurance*, page dated **04/02/2025** — *"the lender must obtain a
primary mortgage insurance policy for a conventional first mortgage loan that has an LTV ratio greater
than 80% at the time it is purchased."* Tier **S → P**; the spec and the bar are updated.

⚠️ **One difference worth your ruling.** The guide states the test **"at the time it is purchased"** — i.e.
when Fannie buys the loan. **MI-1 evaluates the LTV on the file before closing**, which is the
processor-facing question and the earlier of the two moments. They agree on almost every file, but not on
one where the loan amount changes between closing and delivery.

**Question: is the pre-closing LTV the right measurement point for a processor's check**, or should MI-1
say explicitly that it is checking the closing LTV as a proxy for the delivery test?

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

---

## 12. From LP-491 (title: TI-1 · TI-2 · TI-6)

### 12a. ⚠️ Is a vesting mismatch usually a real defect, or a legitimate difference?

**This decides TI-1's direction, and I chose the cautious side without you.** A mismatch between the
commitment's vested owner and the file's counterparty currently returns **`needs_review`, never `fired`**,
because the difference is frequently legitimate — a revocable trust whose trustee is the borrower, an
estate selling, a name changed on marriage or divorce, a deed that has not yet recorded.

**Question: in your experience, is a genuine vesting mismatch usually a real defect?** If it is, TI-1
should fire and I have the direction wrong. If it is usually one of the above, the current behaviour is
right and the finding is a confirmation step rather than a condition.

### 12b. ⚠️ `vesting_type` holds the ESTATE, not the tenancy, on two of four documents

The four real commitments return `fee simple`, `Fee Simple`, `Joint tenants`, `Fee Simple`. Two of those
are an **estate** (fee simple vs life estate) and one is a **tenancy** (joint tenants vs tenants in
common) — different questions in one field. TI-5 would need them separated.

**Question: should the extractor split these into two fields?** That is LP-499's input, and it is why
TI-5 is not built.

### 12c. ⚠️ Do TI-3 / TI-4 / TI-5's fields appear on the source PDFs at all?

`open_liens_indicator` **0/4** · `judgments_indicator` **0/4** · `vesting_marital_recital` **0/4** ·
`schedule_b_items[is_satisfied]` **2/19 rows**. LP-451 called TI-4 a "nearest miss to write-now" because
the *field exists*; the documents say otherwise (ADR-354).

**Question: are these facts printed on your commitments and the extractor is missing them, or are they
genuinely absent from the documents?** The answer decides whether LP-499 is a prompt fix or a dead end.

### 12d. TI-1's vesting vocabulary is unexercised

TI-1 strips `ET UX`, `ET AL`, `HUSBAND AND WIFE`, `AS TRUSTEE OF` and similar before comparing names —
but **all four real commitments carry a plain 2–3 word name**, because the recital goes to
`vesting_marital_recital` (0/4). **Do your commitments normally print the recital inside the vested-owner
line?** If so the extractor is splitting it out and the stripping matters; if not, it is dead code.

### 12e. ⚠️ TI-6 applies no rapid-transfer window

A "rapid transfer" cutoff (90 or 180 days is commonly cited) is an investor-overlay and fraud-review
convention, and **no page was read for it** — so TI-6 hands the interval to the judgment as a fact rather
than comparing it against a number nobody confirmed. **What window do your investors actually use?**

### 12f. ⚠️ Nine judgment rules now ask for a sign-off on every finding, including clean ones

AS-12, CR-8, CR-10, ID-8, ID-9, IN-7, OC-2 and now TI-2 and TI-6. A judgment rule has no `satisfied`
path — a clean title chain produces a `needs_review` identically to a broken one, and TI-2 produces one
per commitment on every file regardless of the answer.

That is the safety design (an AI verdict never auto-ships), and it is what lets these rules go live on an
unmeasured tag. But it is a real load on the processor. **Is a "confirm this is fine" item acceptable, or
should a confident clean answer resolve silently?** The second needs the tag measured first.

---

## 13. From LP-492 (appraisal: PR-2 · PR-3 · PR-4 · PR-5 · PR-7)

### 13a. ⚠️ Should a value shortfall FIRE, or flag?

PR-2 **fires** when the appraisal comes in below the contract price. I chose that over `needs_review`
(which IH-2 and TI-1 use) because a shortfall is not ambiguous the way a name difference is: the number
is the number, and it has a definite consequence — cash, a renegotiation, or a rebuttal.

**Question: is that how a processor wants it?** A low appraisal is extremely common on some files, and
if it is routine in your work it may belong as a flag rather than a defect.

### 13b. ⚠️ Is an appraisal address mismatch usually a real defect?

PR-7 **fires** on a mismatch. PC-3 — the same comparison for the purchase contract — routes ITS mismatch
to `needs_review`, on the reasoning that the canonicaliser does not resolve every surface form (a unit
designator is the known case, ADR-325).

**I made them differ deliberately**: PC-3's mismatch means two documents disagree; PR-7's means the
value in the file may belong to another property. **Question: is that the right split, or should both
behave the same way?**

### 13c. Freddie's stricter condition standard is unbranchable

Fannie: C1–C5 eligible as-is, C6 ineligible, repair to a minimum of **C5**. Freddie: C5 **and** C6
ineligible, repair to at least **C4**. **The agency axis does not exist as a fact on any file** (LP-501),
so PR-5 encodes Fannie's standard only.

**Question: do your files ever go to Freddie?** If so we need a field that says which, or PR-5 will be
wrong on those loans.

### 13d. ⚠️ The UAD 2.6 → 3.6 cutover (Nov 2026)

Both real appraisals are 2.6-era ("9/2011", "9/2011 (Updated 1/2014)") and spell the condition rating
"C4" / "C3". The 3.6 layout may spell it differently. PR-5's vocabulary is closed and **abstains** on
anything unrecognised, so the failure mode is `couldnt_check` rather than a wrong answer — but **every
appraisal rule may quietly stop resolving after the cutover.**

**Question: when do you expect 3.6 documents to start arriving?** That dates the extraction work.

### 13e. What list of property types is actually eligible?

PR-3 carries **no allow-list** — none was obtainable, and inventing one would fire on ordinary
properties. It surfaces a type it cannot place instead. **Question: what is the real list for your
programmes**, particularly around manufactured homes, condotels, co-ops and mixed-use?

### 13f. ⚠️ PR-8 was dropped — where would a disaster declaration come from?

A disaster-area reinspection needs a FEMA declaration. **No field in any of the 121 schema specs, and
nothing in MISMO, states one** — it is external data. **Question: how do you learn today that a property
is in a declared disaster area?** If it arrives as a document or a lender notice, PR-8 becomes buildable.

### 13g. An LTV rounding divergence, reported

Fannie **B2-1.2-01** (06/01/2022) requires the LTV result to be *"truncated to two decimal places, then
rounded up to the nearest whole percent."* Our `ltv.py` rounds **half-up to two decimals**. It affects
MI-1 and PR-1 rather than PR-2, and it can move a borderline file across the 80% line.
**Question: worth fixing before more LTV consumers land?**

---

## 14. From LP-493 (purchase contract: PC-5 · PC-8; PC-1 dropped)

### 14a. ⚠️ What is a "customary" earnest money deposit?

Fannie **B3-4.3-09** (05/04/2022) says large deposits and *"deposits that exceed the amount customary for
the area should be closely evaluated"* — and gives **no number**. I did not invent one, so PC-5 surfaces
the trace and never sizes the deposit.

**Question: is there a working rule of thumb** (1% of price? 2%?) that a processor actually applies, and
does it vary by market? Without one there is no threshold to encode, and that may be correct.

### 14b. ⚠️ A second earnest money deposit is currently lost

Doc 183 stated a **$204,000 additional** deposit distinct from the primary figure. `earnest_money_amount`
is **singular** and there is **no `additional_earnest_money_amount` field**, so only the first is
captured.

**Question: how common is a second deposit on your files?** If it is routine, this is an extraction
change (LP-499) rather than an edge case — and today the larger of the two can be the one omitted.

### 14c. ⚠️ Does contract wording need per-state handling?

Free-text contracts are the least reliable class in our corpus: of ~8 purchase-agreement claims, **one**
was real — the reader projected **Texas TREC** fields onto a **North Carolina** form. PC-8's judgment
abstains on wording it cannot place, which is safe but will abstain often.

**Question: which state forms do you actually see?** If it is two or three, per-form handling is
tractable; if it is a long tail, abstaining is the right permanent answer.

### 14d. Is a party mismatch usually a real defect?

**PC-1 was dropped** — its `title.parties_match` asks the same question **TI-1 already answers**, and a
second matcher on one comparison is what LP-483 forbade. So the question stands for TI-1 instead
(see §12a): **is a mismatch between title's vested owner and the file's counterparty usually a real
defect, or a trust/estate/name-change difference?**

### 14e. ⚠️ Where would arm's-length evidence come from?

`contract.arms_length` was **not built**: its only schema field, `parties_relationship_disclosed`, is
**0 of 5** on the real contracts. FR-2 (fraud lane) is meant to consume this tag later.

**Question: do your contracts disclose a party relationship in a field, or is it something a processor
infers** from matching surnames, an unusual price, or a quick resale? The answer decides whether FR-2 has
an input at all.

### 14f. Personal property — fixture or not?

PC-8 reads free text: "None", "Gas Logs in fireplace", "Refrigerator, Washer/Dryer". A refrigerator is
usually personal property; a built-in oven is a fixture; gas logs normally are.

**Question: where do you draw the line in practice, and at what value does it start to matter?**
`personal_property_value` fills on 1 of 5 contracts and that one reads "0", so no value is available.

---

## 15. From LP-493a — the document PC-5 actually needs

PC-5 (*earnest money traced to a verified account*) is built but held. LP-493a found it abstained because
**it was shown neither the deposit nor any transaction** — two context defects, now scoped — and
separately that no matching debit exists in the fixture we tested on.

⚠️ **Even with those fixed, PC-5 cannot be calibrated on the current corpus**, because LF-6T3N is a
synthetic fixture: its transactions were authored, not extracted.

**What a file would need, specifically:**
1. a **purchase agreement** stating an earnest money amount, **and**
2. **bank statements for the account the deposit actually left**, covering the period it left, **and**
3. ideally the **cancelled cheque or the escrow holder's receipt** — because B3-4.3-09 accepts either of
   those *instead of* a bank debit, and a real file may evidence the deposit that way.

**Question: can you point us at one or two real closed files that carry all three?** It is the same ask
as the credit lane's (§11j) but narrower — this one needs the *asset* side and the *contract* side on the
same file, which LP-480 found is rare in what we hold.

---

## 16. The condo lane — a deadline, a blank form, and a document type we cannot classify (LP-494)

### 16a. ⚠️ A HARD DEADLINE: every condo file changes number on 4 January 2027

Fannie **LL-2026-03** raises the minimum budgeted replacement reserves from **10% to 15%** of annual
budgeted assessment income for **loan applications dated on or after 2027-01-04**. CO-4 keys on the
application date, so it handles the transition correctly — but **nothing in the product tells a processor
it is coming**, and the practical effect is not gradual: an association budgeting 12% is compliant for a
December application and short for a January one, with no change on the association's side.

**Questions for Priya:** should we warn on files near the boundary, and how far ahead? Should a project
budgeting between 10% and 15% be flagged *now*, so an association has time to amend its budget before the
pipeline turns over? **This is the first threshold in the system that expires**, and how we want to handle
date-keyed thresholds generally is a product decision, not an engineering one (ADR-379).

Two related LL-2026-03 changes are already in force and are **not** modelled:
- **The baseline funding method is no longer accepted** for reserve studies (applications on/after
  **2026-08-03**) — a study must adopt its highest recommended funding amount.
- ⚠️ **Limited Review was retired entirely** (applications on/after **2026-08-03** — ten days ago).
  **Does this change what a processor collects on a condo file today?** Previously a Limited Review file
  needed no questionnaire at all; if every condo file now needs a full review, the questionnaire moves from
  sometimes-needed to always-needed, and the needs list should say so.

### 16b. Warrantability still has no source, and now we know it does not need one for CO-5

`property.is_warrantable_condo` remains sourceless (LP-487, confirmed again here) — it is a project-review
conclusion, not a readable datum. **But the tag map was overcautious:** CO-5 does not need a warrantability
verdict. Delinquency, commercial share, single-entity concentration and litigation are each a typed field
on the condo questionnaire, and CO-5 is built on those.

**What warrantability would still need:** Form 1076 / PERS output, or a lender's own project-approval
record. **Is that something the processor ever sees, or does it live only in the LOS?**

### 16c. ⚠️ The blank questionnaire — the real blocker, and it is not a code problem

Both rules are **built and inert**, and the reason is the corpus:
- **No loan file carries a condo questionnaire at all** (0 of 28), and `property_type` is null on every
  file that has documents.
- The bench holds **two** questionnaires: a **cancellation notice**, and a **standard form nobody
  answered**. ⚠️ Verified at the document — the 450 KB form produced 90 catch-all labels against 1 typed
  field, which looks exactly like an extractor defect, but **all 90 carry an empty value**. The form asks
  the questions; the answers are not there.

**Question: is a blank questionnaire normal?** If associations routinely return them unanswered, that is a
process finding worth more than either rule — a processor should be chasing the completed form, and CO-1
(live) already reports the document as present, which may be actively misleading. **One completed
questionnaire unblocks both rules with no code change.**

### 16d. HOA budgets have no document type

The catalog assumed AI would parse an HOA budget for the reserve percentage. **There is no HOA-budget
document type**, so a budget cannot be classified, extracted, or attached — budgets in the bench routed to
`unknown`. The reserve percentage is instead read from the questionnaire's `reserve_contribution_percentage`.

**Question: do processors receive HOA budgets as separate documents?** If so, a catalog type + extractor is
a small piece of work and gives CO-4 a second, independent source — useful, since the questionnaire's
stated percentage is self-reported by the association.

### 16e. CO-3 was dropped — and IH-7 has a gap worth deciding on

CO-3's master-insurance half duplicates live **IH-7** (ADR-375), and its fidelity half cannot be computed:
B7-4-02 (08/05/2026) exempts projects of **20 units or fewer** and sets the required amount at **three
months of assessments on all units**, so both the gate and the amount need a unit count and an assessment
base that no document on file provides.

⚠️ **A correction found here:** the master policies *do* carry `fidelity_crime_coverage_present` and
`_amount` (8/8 on the bench). **The coverage reads fine; the requirement is what cannot be computed.**
So the leg is one completed questionnaire away, and it belongs **inside IH-7** — one rule, one verdict on
the master policy — not as a second rule.

### 16f. Single-entity ownership — the conflicting figures resolved

Two sources gave **>20%** and **10%**. **Neither describes the rule.** B4-2.1-03 (08/05/2026, fetched) is
**tiered**: 20% for projects of 21+ units, a maximum of **2 units** for projects of 5–20 units, and **no
stated limit below 5 units** — where CO-5 abstains rather than inventing one.

⚠️ **One discrepancy against the ticket, reported:** the ticket gave non-incidental business income as
"may not exceed 15%". The primary makes **more than 10%** ineligible, with 15% permitted only under
specific exceptions. **Not modelled** (no field carries it), but worth correcting wherever the 15% came
from.

### 16g. Still open from LP-492 — the LTV rounding rule, now confirmed against the primary

**B2-1.2-01, page dated 06/01/2022 (tier P, fetched):** *"The result of these calculations must be
truncated (shortened) to two decimal places, then rounded up to the nearest whole percent."*

`app/verification/ltv.py:103` uses `ROUND_HALF_UP` **to two decimal places** — two divergences: it rounds
half-up rather than always up, and it does not round to a whole percent at all. **Affects MI-1 and PR-1.**
Confirmed and reported only, not fixed here; **no ticket exists for it yet.**

---

## LP-495a — letters of explanation, and the retention question reopened

### 1. ⛔ What conditions REQUIRE a letter of explanation? (blocks LO-1)

LO-1 ("LOE required-and-present") cannot be built without this list, and **nothing in a loan file
enumerates it.** It is lender- and AUS-driven: a DU/LPA message, an investor overlay, or an underwriter's
condition creates the requirement, and none of those is a document the system reads.

The only source available inside the system is **the run's own findings** — which would make LO-1 a
**meta-rule over other rules' output.** No rule in the engine does that today (every rule reads fact-tags
derived from documents and MISMO), so it is an architectural change, not a build step. **LO-1 is held.**

**What would unblock it:** a list, even a partial one, of the conditions that in practice require a
borrower LOE — e.g. credit inquiries in the last 90 days, a prior derogatory event, an employment gap, a
large or irregular deposit, an address discrepancy. A ranked "always / usually / lender-specific" split
would be more useful than an exhaustive list.

### 2. Is an UNSIGNED letter of explanation a FINDING or a CONDITION?

LO-2 currently routes an incomplete letter to **`needs_review`**, not `fired`. Two reasons, and the
second is the one we would like confirmed:

- **Evidence:** on the one LOE type whose extractor carries the fields, `referenced_date` fills 6/9 and
  `borrower_signature_present` 7/9, so an empty field cannot be distinguished from one the extraction
  missed. Firing would assert a defect on a letter that may well be signed and dated on the page.
- **Domain:** we do not know whether an unsigned LOE is something a processor must FIX before submission
  (a finding) or something underwriting routinely conditions for (a condition). If it is genuinely the
  former, LO-2's `incomplete` outcome should be reconsidered once extraction is more reliable.

### 3. Does a 1003 REO section ever reach processors?

This would **reopen the retention question properly.** RE-1 and DT-6 now reconcile mortgage statements
against the application's stated MISMO liabilities and deliberately **surface** a discrepancy rather than
**assert** retention — because "this property is being RETAINED" is an inference that no document,
extractor field or MISMO fact in the system states. `property.is_retained_reo` and
`property.retained_pitia` remain vocabulary orphans with no producer.

A real REO schedule (or the 1003's owned-property section) would carry the disposition — retained /
pending sale / sold — and would let a rule state the DTI consequence directly instead of asking a
processor to. **Do processors ever receive one?** If so, in what form, and from where in the origination
flow?

### 4. Two extraction gaps found while building LO-2 (reported, not fixed)

- **`credit_explanation_letter` has NO extractor.** It is a real classifier type and 4 documents in the
  corpus classify as it; all 4 record status `no_extractor`. They are letters of explanation that the
  system can see but cannot read.
- **The six LOE variant extractors capture different fields from each other.** Only the base
  `letter_of_explanation` captures an explanation summary, a referenced date and a signature indicator;
  the variants capture `letter_date` / `reason_or_cause` / `borrower_certification` instead. Is the
  distinction between "the date of the event explained" and "the date the letter was written" one
  processors care about, and should the variants capture a signature indicator too?

## LP-496a — program eligibility (PE-1 / PE-3)

### 1. How does a processor determine the applicable county conforming limit in practice?

PE-1 currently abstains for any conventional loan whose amount falls between the national baseline
($832,750 for one unit in 2026) and the high-cost ceiling ($1,249,125). In that band the answer
depends entirely on the subject property's county, and the loan file does not carry a county today.

- Where does a processor look this up — FHFA's published county file, the LOS, the AUS findings, or
  the lender's own matrix?
- Is the county the processor uses always the property's county, or does anything else (an MSA, a
  metropolitan division) come into it?
- How often does a file in this band actually arise? If it is rare, the abstain costs little; if it
  is common in our markets, restoring the county becomes urgent.

### 2. Does an FHA case number reach the processor before submission, and on what document?

PE-2 is **held** because the datum has no source: no extractor field, no FHA document type among the
classifier's 163, and zero hits across all 2,558 raw corpus PDFs.

- Is the case number assigned before or after the processor assembles the file?
- Which document carries it in practice — the case number assignment printout, form 92900-A/LT, the
  AUS findings, or only the LOS screen?
- Should the system expect one at all at this stage, or is PE-2 checking something that legitimately
  does not exist until later?

### 3. Are inducements to purchase visible anywhere in a file?

PE-3 computes FHA's Adjusted Value as the lesser of purchase price and property value, **without**
the "less any inducements to purchase" deduction HUD 4000.1 requires, because nothing in the snapshot
represents inducements (0 of 19 loan files carry any such field). The omission is one-directional and
safe — it can only raise the required investment, never clear a failing file — but it can raise a
false condition.

- Where do seller inducements/concessions actually appear: the purchase contract, an addendum, the
  closing disclosure, or the appraisal's sales-concession adjustment?
- Are they usually itemized, or embedded in a "seller paid closing costs" figure?
- Is the distinction between a seller credit toward closing costs and an inducement that reduces
  Adjusted Value one that processors track explicitly?

### 4. What the research could not obtain

- **The 2-4 unit conforming limits.** FHFA's release states one-unit figures only; the multi-unit
  values ship inside the downloadable county file, which was not transcribed this ticket. PE-1
  therefore abstains on any multi-unit property rather than judging against an unverified number. Is a
  2-4 unit conventional purchase common enough for this to matter?
- **HUD 4000.1's MPR/MPS section** was not cited (PE-4 is held on other grounds anyway). If PE-4 is
  ever built, which condition callouts do processors actually see FHA appraisers write?
- **FHFA's "6 counties moved into high-cost"** figure could not be verified; FHFA's own release states
  only that values rose in "all but 32" counties.

## LP-497 — reserves and NSF (AS-4 / AS-5)

### 1. What were you answering when you labelled the five reserve-eligibility cases `no`?

All five were standard checking/savings accounts, and the model called them reserve-eligible. LP-497
diagnosed the disagreement as a question mismatch rather than a model error: the prompt asks about
**account type**, while the `no` appears to mean **"these funds are the down payment / EMD, so they
are not reserves for this loan"** — which is the funds-to-close rule, and which `compute_reserves`
already applies at loan level.

- Is that reading right? If so the tag was asking the wrong question and AS-4 no longer depends on it.
- If it is **not** right — if `no` encoded a lender overlay, or a restriction on those specific
  accounts — then we have removed a real signal and need to know what it was.
- More generally: when you assess reserve eligibility, are you judging the **account** or the
  **remaining balance after closing**?

### 2. Is your NSF tolerance a firm policy value we can encode?

The Selling Guide sets no NSF or overdraft count tolerance — confirmed by research, matching your
ruling that it is internal policy. AS-7 therefore reports the count and passes no verdict on it.

- Is there a count that triggers a condition in practice (any NSF? three in twelve months?), and does
  it vary by lender?
- Does **event type** change it — a returned ACH vs a paid-into-overdraft item vs a returned check?
- Should an NSF on a **business** account be treated differently from a personal one?

### 3. The FHA retirement factor

`reserves.py` applies a `0.60` factor to retirement assets for FHA and `1.00` for conventional. The
conventional side matches the guideline (Fannie applies no haircut, confirming your ruling that the
60/70% figures are not Fannie's). The FHA `0.60` predates this work and carries no citation in code.

- Is 60% the right FHA figure today, and where does it come from?

### 4. What the research could not obtain

- **B3-4.1-01's month counts were fetched** (tier P) — that gap is closed. What is **not** modelled is
  the 2%/4%/6%-of-aggregate-UPB overlay for other financed properties, because neither the financed-
  property count nor the aggregate UPB reaches a loan file. How often does a borrower with other
  financed properties reach you, and where would that count come from?
- **The cash-out-refinance-over-45%-DTI cell** is likewise not modelled — is that combination common
  enough to matter?

## LP-498 — the fraud cohort (FR-1 … FR-6)

### 1. What do you actually do when a document looks altered?

FR-1 was not built: its tag is asked about font inconsistency and pasted figures, but an AI group
receives extracted field VALUES, never a rendering, so it cannot see what it is asked about.

- When a document looks altered, do you flag it in the file, or does it leave the file entirely — a
  call to the LO, an escalation to compliance, a SAR conversation?
- If it leaves the file, a rule that writes a finding into the loan file may be the wrong shape
  regardless of whether we can detect it. Should the system surface this at all?

### 2. Is an unusual seller credit your call or the underwriter's?

FR-3 now surfaces contracts whose credit terms or side-agreement references merit a look. It routes to
needs_review and asserts nothing.

- When you see a large or oddly-purposed seller credit, do you act on it, or is it underwriting's?
- Does a **side agreement** referenced in the contract change your workflow — do you request it?
- The first derivation disagreed with itself on a routine $3,000 closing-cost credit, one call saying
  "review it to verify terms align with guidelines". Is that right — should a processor look at every
  credit, or only unusual ones? I built it as *only unusual ones*; tell me if that is wrong.

### 3. What does a garnishment on a pay stub oblige you to do?

FR-4 was not built — it asks a bank-transaction tag about a pay-stub deduction, and the corpus carries
zero real garnishments in 2,557 documents.

- Do you see garnishments in practice, and on which document?
- Does one become a liability in the DTI, a condition, or a conversation with the LO?

### 4. The FHA 90/180-day flip window is now citable — for FHA only

24 CFR 203.37a is verified (GPO, edition 2024-04-01): a resale **90 days or less** after the seller's
acquisition is **not eligible** for FHA insurance; **91–180 days** with a resale price **100% or more**
above the seller's purchase price requires a **second appraiser**. The period runs from the seller's
settlement date to the date the sales contract is executed.

**This resolves TI-6's tier-U rapid-transfer window for FHA files.** Conventional has no codified rule
— lenders impose one as an overlay.

- Does your shop carry a conventional flip overlay, and what is its window?
- The regulation exempts **eight** categories, including inherited property, employer/relocation
  acquisitions, and state/local government agencies. Do those come up?

### 5. What the research could not obtain

- **B3-4.1-02's per-cell IPC table** remains tier U. FR-3 does not test the cap — that is PC-4's
  function (agency-gated to LP-509). If you want FR-3 to test the limit rather than surface terms for
  review, the table needs fetching first.
- **No governing standard exists** for document alteration, recurring-debit patterns or open-ended
  discrepancy discovery. Fannie's fraud material describes red flags and reporting obligations on the
  *institution*, not tests for a processor's checklist. Is there a lender-side policy we should encode
  instead?

## LP-516 — AS-12 borrowed funds

1. **Is a transfer from an UNVERIFIED account exempt?** Fannie B3-4.2-02 exempts "a transfer of funds
   between **verified** accounts". Nothing in the snapshot can establish that the counterparty account
   is verified (`stmt.account_masked` is "display only, non-matchable"; a transaction description has
   every 9+-digit identifier redacted), so today `transfer_own` is NOT exempt and still reaches a human.
   On LF-WCHG that is 6 findings: $1,000–$3,000 round-dollar transfers from a credit union whose
   statements appear nowhere in the file. Is that the right call, or should an own-account transfer be
   exempt regardless of whether the other account is documented?
2. **A large round-dollar own-account transfer shortly before closing** — does proximity to closing
   change the answer to (1)?
3. **What is an acceptable number of ratifications per file?** Not an AS-12 question: nine live judgment
   rules route EVERY verdict to `needs_review`, so the count scales with the rule set rather than with
   what is actually wrong on the file. "As few as are real" is not something a rule can be written
   against.
4. **Confirm the 50% threshold for AS-12** if the purchase-side materiality test is built. AS-1 already
   uses it and its own spec records it as not yet confirmed.
