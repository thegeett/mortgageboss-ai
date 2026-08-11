# Missing extractors — plan

_From `_MISSING_EXTRACTORS.md` and the live `no_extractor` listing._

---

## ⚠️ First: the headline number is stale

The report says **64 documents**. The live listing shows that is no longer true.

| what the report counted | status now |
|---|---|
| **`unknown` 31** | ⚠️ **Mostly built since.** Buydowns (059/067/068), USCIS (062/065), HVE (061/063/070/197), ACORD 25 (073), invoices (058/064/072/210), wire (154/158) — **all now have types** from LP-465/466/467 |
| **`0.0` confidence rows** — 60, 66, 69, 75, 272-276, **277-280 (the same four, re-run)** | ⚠️ **AI-call failures already fixed** by LP-462 and LP-464 |
| **`visa_documentation` 187/188/240** | ⚠️ **Absorbed by `uscis_notice_of_action`** (LP-465) |

**The real remaining gap is ~22 documents across 6 types — not 64.**

---

## ⚠️ Second: the CD does NOT unblock the closing rules

The report ranks `closing_disclosure` first on the assumption it feeds CL-1/2/3. **It does not.**

| rule | status | what it actually reads |
|---|---|---|
| **CL-1** rate-lock expiration | EXTRACT | **a rate-lock confirmation** — not the CD |
| **CL-2** clear-to-close conditions | BLOCKED | *"Post-submission — out of pre-submission scope"* |
| **CL-3** final CD accuracy | BLOCKED | *"Out of pre-submission scope"* |
| CL-4 · CL-5 · CL-6 · CL-7 | BLOCKED | out of scope |

**And every DC rule that reads a CD or LE is marked `SCOPE?` — *"likely an LOS function, confirm scope."***

⚠️ **So the CD and LE schemas serve NO rule that is currently in scope.** They earn their place on
**processor visibility**, exactly like wire instructions and the ACORD 25 — **not on rule coverage.**

**That matters for how much to build.** The CD is the densest document in a loan file — ~140 fields, party
blocks, projected payments, two cost tables, cash-to-close, borrower *and* seller summaries, payoffs, loan
calculations, escrow, an ARM table. **Easily four nested lists.**

⚠️ **Building all of it for zero in-scope rules is disproportionate.** **Build the headline block, and let
Tier 3 free extraction carry the rest until a rule needs it.**

---

## The six types

### 1. `closing_disclosure` · 8 docs (161-168) · **all 0.95-0.99**
⚠️ **167 is a closing PACKAGE** (CD + 1003 + closing instructions) → **splitter work, not this.** So 7.

**Scope: the headline block only.** Closing/disbursement dates, settlement agent, parties, loan terms,
**APR / finance charge / amount financed / TIP**, total closing costs, cash to close, and — if cheap — the
**payoffs** list.
⚠️ **Do NOT build the full A-J cost tables, both transaction summaries, and the ARM table** until DC-4 or
DC-5 is confirmed in scope.

### 2. `loan_estimate` · 3 true (258, 259, 260) · **0.98-0.99**
⚠️ **204 is a misclassified 73-page 1003 package** → not an LE.

**~80% shared with the CD schema — build them together.** LE-specific: the **"In 5 Years"** comparison box,
rate-lock and closing-cost **expiration dates**. No seller column, no payoffs.

### 3. `general_correspondence` · 6 docs
⚠️ **154 and 158 leave for `wire_instructions`** (LP-466); **157 is an e-signature Certificate of
Completion** — a different genre.

**The genuine remainder is ~5 LOX/underwriting emails** (152, 153, 156, 159, 214). **A thin schema:**
from/to, sent date, subject, a body summary, an attachments list.
⚠️ **Do NOT build a "key facts" area** — employment rows, addresses-in-dispute, LOE questions vary per
letter. **That is precisely what Tier 3 free extraction is for.**

### 4. `passport` · 2 docs
⚠️ **266 is `H4EAD-23-26` — an Employment Authorization Document classified as a passport at 0.92.**
**That is a MISCLASSIFICATION, not a passport.** The immigration family again (a UK passport previously went
to `permanent_resident_card`).

**So: 1 real passport (264, Indian, field-rich) + 1 classifier problem.** ⚠️ **An EAD may deserve its own
type** — it is work-authorisation evidence, which **ID-8** reads. **Decide that before building.**

### 5. `1098` · 2 docs (243, 244) — same lender, same borrower
⚠️ **Check the catalog first.** The report says `1098` is absent, but ~70 types were added in LP-442.
**If present → spec only. If absent → a full type addition.**

**Simple schema:** payer/lender (name, address, TIN), borrower (name, masked TIN), account number,
**Boxes 1-11**, tax year. **Mortgage interest and property taxes are DTI-relevant** — a real, if indirect,
rule tie.

### 6. `commission_income_statement` · 3 docs (245, 246, 247) — ⚠️ **DO NOT BUILD**
This is a **mortgage sales-commission** type being used as a dumping ground for **employee compensation
statements** (Deloitte, PayPal, Fidelity). **Building its extractor would cement the wrong routing.**

⚠️ **And LP-463 may already have fixed it** — 246 and 248 declined honestly in that ticket's proof and
free-extracted their salary, bonus and equity.
**RE-CLASSIFY ALL THREE FIRST.** If they now decline, the correct fix is a `compensation_statement` type
(missing-types work), **not an extractor for the wrong type.**

---

## The order

| # | work | docs | why |
|---|---|---|---|
| **1** | **Re-classify 245/246/247, 266, and check the `1098` catalog entry** | — | ⚠️ **Free. Three of the six may be smaller or different than the report assumes.** Do this before scoping anything |
| **2** | `1098` | 2 | Smallest real schema; **DTI-relevant**; likely just a spec |
| **3** | `passport` (+ an EAD decision) | 1-2 | **ID-1 / ID-8**; the only genuine rule tie in the set |
| **4** | **CD + LE together** | 10 | Largest data volume; ⚠️ **headline block only** — no in-scope rule |
| **5** | `general_correspondence` | ~5 | Thin schema; Tier 3 carries the per-letter facts |
| **—** | `commission_income_statement` | 3 | ⚠️ **Do not build. Re-route instead** |

---

## The principle this plan applies

**A type earns a schema when a rule reads it, OR a processor needs it reliably.**

- **1098 and passport** — a rule tie
- **CD, LE, correspondence** — processor visibility only, **so build the headline and stop**
- **commission_income_statement** — neither; it is a routing error

⚠️ **And Tier 3 is no longer nothing.** Since LP-463 it is scoped free extraction landing in a marked-untyped
snapshot section, readable by AI cross-source verification. **"No extractor" now means "no rule can use it,"
not "nothing captured."** That lowers the urgency of everything on this list.
