# Extraction accuracy — the wrong-value problem

_Filed 2026-08-10. **Deferred work, with its motivating evidence.** The comparison report called this **P11**._

---

## The problem in one line

**A missing field is safe. A wrong field is dangerous.**

A missing field returns `couldnt_check` and a human looks at it. **A wrong field returns a confident wrong
verdict and nobody knows.**

⚠️ **Nothing in the pipeline currently checks whether an extracted value is CORRECT.** Coverage is measured;
accuracy is not.

---

## The motivating case — LP-469, document 244

A RoundPoint **Form 1098** prints two things:
- a **cover letter** at the top, prominently showing **"Real Estate Taxes Paid $2,537.21"**
- the **IRS form grid** below, where **Box 1 — Mortgage interest received — is $4,472.97**

**The extractor returned `mortgage_interest_received = $2,537.21`** — the taxes figure from the cover letter.

### Why this one matters
**Box 1 feeds DT-6** (the housing expense on a retained property) — and these documents **are** that case:
Box 8's property is in **Washington** while the borrower's address is **North Carolina**.

**$2,537 in place of $4,473 understates the annual interest by nearly half.**

### ⚠️ Why prompting does not fix it
- An explicit Box-1-vs-cover-page disambiguation hint was added **twice, escalating**.
- **244 returned $2,537.21 stably across every run.**
- **243 — same servicer, same layout — stayed correct throughout.**

**So it is this particular scan, not the template.** The hint was kept (correct guidance, 243 unaffected) and
the document filed as a known wrong value.

---

## ⚠️ Is this because of Haiku? Probably a factor — but do NOT assume it is the whole story

**Honest answer: unmeasured.** The switch to Haiku (LP-457) was verified on **two documents** — a credit
report and a pay stub — and matched Sonnet on both, including all 18 tradelines. **That is not enough to
conclude Haiku is equivalent on dense or ambiguous layouts.**

**Arguments it is a Haiku limit:** this is a visual-anchoring judgment (two plausible dollar amounts, one
prominent and wrong, one in a small numbered box). Larger models generally do better at that.

**⚠️ Arguments against blaming the model:**
- **243 is the same servicer and layout and was extracted correctly by the same model.** A model-capability
  ceiling would not be document-specific.
- **The same class of error appeared on SONNET** in the free-reader comparison — a tradeline payment scaled
  **100× too high** ($269,430 vs $2,694), a $650 deposit read as $2,650, digit transposition on a coverage
  amount. **Different model, same failure class.**
- Our own pipeline **beat** the free reader on exactly these numeric-column cases in ~20 documents.

**Conclusion: a stronger model would probably reduce the rate. It would not eliminate the class.**

### ⚠️ The cheap test, if this is worth settling
**Re-extract 244 on Sonnet and compare.** One document, a few cents. **If Sonnet gets Box 1 right, a
per-type model tier becomes a real option** (`form_1098` is small and low-volume). **If Sonnet fails too,
the answer is the audit layer, not the model.**

**Do this before spending anything on a model upgrade.**

---

## The same class, elsewhere in the corpus

| document | the wrong value |
|---|---|
| **244** | Box 1 interest ← the Box 10 taxes figure |
| **250** (free reader) | every tradeline payment scaled **100×** — $269,430 vs $2,694 |
| **251** (free reader) | "30" appended to every payment — $2,530 vs $25 |
| **047** (free reader) | a $650 Zelle deposit read as $2,650 |
| **credit report** | a fabricated day-of-month across **21 tradelines** |
| **113** (free reader) | digit transposition on a condo Coverage A |

⚠️ **Both readers produce these. It is a class, not a model.**

---

## The fix — deterministic self-consistency checks (P11)

**Not a better prompt. Arithmetic the document itself supplies.**

| check | catches |
|---|---|
| **Box 1 ≠ the amount inside Box 10's text** | ⚠️ **244 exactly** — interest and taxes being identical is near-impossible |
| beginning + deposits − withdrawals = ending | 047, 049 |
| gross − deductions = net | pay stub arithmetic breaks |
| **Σ(tradeline monthly payments) = the declared total** | ✅ **already proved a credit report complete in LP-445** (1432 = 1432) |
| a date sanity range | the fabricated day-of-month; a 1925 issue date |
| a declared count vs actual row count | ✅ **already built** — the `*_count` cross-checks |

### Why this is the right shape
- **Model-independent** — it keeps working when the model changes, which matters now that extraction is on
  Haiku and may move again
- **Deterministic** — no calibration, no Priya time, no labelling round
- **Cheap** — arithmetic on values already extracted, no extra AI call
- **Precedented** — the `*_count` cross-check already exists and already caught a real problem

### ⚠️ What it must NOT do
- **Never silently "correct" a value.** Flag it — **PARTIAL**, or a finding for review. **A pipeline that
  repairs its own inputs is worse than one that reports them.**
- **Never fire on a legitimate coincidence.** Some checks will occasionally match by chance; the outcome is
  *needs review*, never a hard failure.

---

## Status

**Deferred.** ⚠️ **Do this after the extractor work finishes, not instead of it** — but before writing tags
at scale, because a tag built on a wrong value is worse than a tag built on a missing one.

**244 remains a known wrong value.** Not chased: one document, resistant to prompting, and the alternative
was a model upgrade for an entire type.

**Related deferred items:** the splitter · bank_statement Option 3 · the 89 untuned starter prompts ·
classifier image preprocessing (rotated ID cards) · the agency-versioned rule structure.
