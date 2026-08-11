# Classification remediation plan

_From `_CLASSIFIER_ERRORS.md` — 54 of 268 documents (20%) misclassified._

---

## The finding that shapes everything

**Confidence does not predict correctness.** Wrong calls ran from **0.75 to 0.99**. A confidence threshold
would suppress correct high-confidence calls and still miss the wrong ones.

**So the fix is not a threshold.** It is: let the classifier decline, stop overriding its own judgment, and
make declining cheap.

---

## The four problems, and which are really about classification

| # | problem | docs | is it a classifier judgment error? |
|---|---|---|---|
| **A** | **The system contradicts itself** — the reasoning names one type, the label says another | 3 (158, 246, 248) | **No — a design flaw.** The model was right and something discarded it |
| **B** | **Infrastructure failures** — the AI call never completed | 8 | **No.** Four oversized payloads, four rate-limit rejections |
| **C** | **No correct answer exists** — the catalog has no matching type | ~11+ | **No.** A catalog gap; belongs to the missing-types work |
| **D** | **Genuinely similar documents** confused with each other | ~14 | **Yes** — and concentrated in one family |

**Only D is a judgment problem.** Most of the 20% is the system being forced into a bad answer or failing
before it got one.

---

## PHASE 1 — Infrastructure _(8 documents, no judgment involved)_

**Four `BadRequestError` — oversized payloads.** 060 (141pp / 3.3MB), 066 (148pp), 069 (118pp / 2.58MB),
075 (177pp / 10.85MB Declaration of Condominium). ⚠️ **Bedrock rejected these, not our code.**

**Fix:** send only the first N pages for **classification**. A Declaration of Condominium is identifiable
from page one — 177 pages are not needed to name it. *(Extraction is a separate question and may need more.)*

**Four `RateLimitError` — four consecutive documents.** 273 (condo appraisal), 274 + 275 (1120-S packages),
276 (CD statement). ⚠️ **All four are types the catalog handles correctly if the call completes.**

**Fix:** catch the rate-limit error and **retry with exponential backoff**. The existing limiter paces steady
throughput; it does not recover from a rejection.

**Cheapest phase, no design decisions, recovers 8 documents.**

---

## PHASE 2 — Let the classifier decline, and stop overriding it

**Geet's decisions:**
> **Do not force a document into one of the 108.** If nothing genuinely fits → **`unknown` or
> needs-review**, with **full free extraction**.
> **Reasoning-vs-label disagreement → flag for review.**
> **Remove Tier 3.**

### 2a — Declining must be a legitimate answer
Today the classifier picks the nearest match because declining costs everything (Tier 3 = near-nothing). **So
it is effectively pushed to guess.** With free extraction behind it, declining becomes cheap and honest.

**Also worth building in: ask the model to NAME the document before choosing a type.** On 158 it already wrote
*"wiring instructions from a law firm"* — **the free-text name was more reliable than the constrained pick.**

### 2b — The reasoning-vs-label guard
Both a label and a free-text explanation are produced today, and **nothing compares them.**

- **158** — reasoning: *"wiring instructions from a law firm"* → labelled `general_correspondence` (0.85)
- **246, 248** — the reasoning openly admits the fit is wrong; the label is applied anyway

**When the explanation names a type different from the label → flag for review, do not apply the label.**

⚠️ **Why this matters more than it looks.** These three were relatively harmless *because the mislabelled
types have no extractor* — nothing was force-populated. **But the same mechanism produced the T4 case in an
earlier batch: a Canadian T4 labelled `w2`, with the US W-2 schema applied, while the reasoning said "this is
a T4."** That produces plausible American tax numbers from a Canadian form — and nothing downstream would
notice.

**Keep the negative indicator (T4 is not a W-2) so it cannot regress**, and re-check the Canadian T4 files
elsewhere in the corpus.

### 2c — Remove Tier 3
Generic analysis goes. A document with no matching type gets **free extraction**: the model reads it and
returns what it finds, untyped.

⚠️ **The standing constraint:** free-extraction output is **model-labelled and uncoerced**, so **no
deterministic rule may depend on it** — the same reason the catch-all cannot be trusted. It is for the
processor to see, and for an AI reasoner to weigh. **Not a rule input.**

### ⚠️ GEET'S DECISIONS — settled

**Tier 3 KEEPS ITS NAME; its behaviour changes.** It is no longer generic analysis — it becomes **free
extraction scoped to mortgage-relevant data only.** The model reads the document and returns what matters to
a loan file (parties, amounts, dates, account and property identifiers, obligations), **ignoring boilerplate,
legal disclaimers and page furniture.** ⚠️ **Not "extract everything"** — that is what fills a W-2 with 35
fields of IRS notice text.

**Output goes to a MARKED-UNTYPED SNAPSHOT SECTION.** Visible to a processor, and — the point of the design —
**available to AI cross-source verification**, which can weigh it against typed data from other documents.
⚠️ **No deterministic rule may depend on it**: the labels are model-chosen and the values uncoerced, the same
reason the catch-all cannot back a rule.

**"Flag for review" means classification did not succeed.** The UI shows a yellow *needs review* marker, and
the document **still routes to Tier 3 for free extraction**. It is not a dead end.

**Order of operations is unchanged:** every document is classified against the 108 catalog types first.
**Free extraction is the fallback when nothing fits — never the default.**

---

## PHASE 3 — The genuinely confusable pairs · ⚠️ DEFERRED, re-measure first

⚠️ **Geet's caution, and it is the right one:** hard-coded distinguishing cues are brittle and do not scale to
108 types. **Do not write cues for every pair.**

**DECISION: do Phases 1 and 2, then re-run a sample and see whether the confusion persists.**

**Why defer:** once the classifier can decline, a middling-confidence Loan-Estimate-vs-Closing-Disclosure call
becomes an honest unknown rather than a wrong label. **Phase 2 may resolve most of this**, and adding cues in
advance sets a precedent that invites doing it for all 108. **Add them later with evidence, if the confusion
survives.**

**If it does survive, this one family is worth the exception** — common documents, expensive to confuse (the
closing rules depend on the distinction), and the separators are concrete:

| type | the distinguishing cue |
|---|---|
| **loan_estimate** | *"Estimated"* throughout · an **"In 5 Years"** comparison box · rate-lock expiration |
| **closing_disclosure** | a **disbursement date** · a **seller transaction column** · payoffs · a "Confirm Receipt" signature block |
| **mortgage_statement** | **"Amount Due by [date]"** · running principal/escrow balance · payment history · **no APR/TIP, no cost tables** |

**Everything else on the confused-pairs list is really a missing type** (compensation statement, wire
instructions, HOA budget, lease amendment, e-sign certificate) — **and Phase 2 handles those correctly by
declining**, which is better than a cue.

---

## Recorded for later _(not this plan)_

- **Missing types** — the next report in Geet's order; Phase 2's declines will size it
- **Multi-document PDFs** — 167 is a CD + a full 1003 + closing instructions; **271 is a two-employer W-2
  package where the classifier locked onto a small 1099-INT and dropped ~$173k of wages.** One label per file
  cannot represent these; a splitter is its own piece of work
- **bank_statement Option 3** — the proper `accounts[]` restructure
- **The LOE type problem** — 155/213 forced into a credit-inquiry-shaped schema
- **89 untuned starter prompts** (LP-459)

---

## Order and reasoning

**Phase 1 first** — pure infrastructure, no decisions, recovers 8 documents.

**Phase 2 next** — it is the substantive change, and **it makes Phase 3 smaller**: once declining is
legitimate, most "confusions" resolve to honest unknowns rather than wrong labels.

**Phase 3 last, and narrow** — one family only, because the separators are concrete and the confusion is
common. Not a general strategy.
