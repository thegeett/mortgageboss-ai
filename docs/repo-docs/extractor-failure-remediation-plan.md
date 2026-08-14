# Extractor-failure remediation plan

_From `_EXTRACTOR_FAILURES.md` — 10 documents with a correct schema and a correct classification that
**errored to a completely empty result** (every field null, every list empty, catch-all empty)._

---

## What makes this different from every gap we have worked on

The document was classified correctly. The right schema was found. **The extraction call started and then
died before emitting anything.**

**So this is not a narrow schema, a missing field, or a misread value. The code broke.** That is why it needs
diagnosis before it needs a fix.

---

## ⚠️ What is EVIDENCE and what is INFERENCE — read this before planning the fix

### Evidence
| type | failed | succeeded |
|---|---|---|
| **lease_agreement** | 3 long multi-page standard forms (174, 175 @ 38pp, 176) | 2 short single-page extension addenda (177, 178) |
| **property_profile_subject** | 198 — the full AVM report | 200 — the shorter profile (14/25 fields) |
| **uniform_residential_loan_application** | **2 of 2** — both full multi-section packages | — |

**9 of 10 failures are `ValueError`. One (appraisal 272) is `RateLimitError` — a different problem entirely.**

**Prior repo notes rule out token truncation:** every failure recorded `failure_reason: none` and none neared
the token cap. **So the response was not cut off** — the failure is earlier than that.

### ⚠️ Inference — NOT established
**"Long documents fail" is the best available hypothesis, not a finding.** Five data points, and *length is
confounded*:
- Long documents are also more likely to be **scanned**, **multi-section**, or **table-heavy**.
- ⚠️ **174 is specifically noted as "likely scanned/image-based — defeated pypdf text on both readers."**
  **That is a different cause that happens to also be long.**

**Do not build a fix on the correlation. Establish the cause first.**

### ⚠️ A specific hypothesis worth testing first
**LP-462 proved Bedrock rejects oversized CLASSIFICATION requests** (4 documents, 118–177 pages). It was
fixed by capping classification to 15 pages. **Extraction still sends the whole document.**

**If the error handler converts a Bedrock payload rejection into a `ValueError`, this is not a parse bug at
all — it is LP-462's problem, unfixed on the extraction side.** That would explain the length correlation
exactly. **Test this before anything else.**

---

## What `ValueError` actually tells us: nothing useful

It is a **generic Python error** meaning "a value was not what the code expected." It is raised by numeric
conversion, date parsing, structural unpacking, and dozens of other operations.

**We have a symptom with no location.** ⚠️ **The first job is capturing the traceback and message** — the
line that raised it. Without that, any fix is a guess.

---

## PHASE 1 — DIAGNOSE (no fix)

1. **Capture the traceback.** If the current handler swallows it, **fix the logging first.** Every step below
   depends on knowing where the error is raised.
2. **Test the payload hypothesis** — is the `ValueError` a converted Bedrock rejection? **Cheapest to rule in
   or out, and it would change the whole fix.**
3. **Reproduce on a matched pair — same type, different length:**
   - `lease_agreement` **175** (38pp, fails) vs **177** (1pp addendum, succeeds)
   - `uniform_residential_loan_application` **206** (fails) vs — no short control exists; use another type
   **A matched pair is what separates length from structure.**
4. **Check 174 separately.** If it is image-only, it is a **scanned-document** problem, not this bug.
   ⚠️ **Do not let one cause hide inside another.**
5. **Report the root cause(s).** ⚠️ **It may be more than one** — the pattern is suggestive, not proof.

**Output: what raised the error, on which documents, and whether it is one bug or several.**

---

## PHASE 2 — FIX

Scope depends entirely on Phase 1. The three candidate shapes:

| if the cause is | the fix |
|---|---|
| **an oversized payload** | page-capping or chunking for extraction — the LP-462 pattern, applied here. ⚠️ **But extraction genuinely needs more pages than classification** — a 15-page cap would lose a 1003's later sections |
| **a parse/validation error** | harden the specific path, with a regression test on the failing structure |
| **scanned / image-only input** | a separate concern — OCR or an honest "unreadable" outcome, not a parse fix |

### ⚠️ Regardless of cause — a permanent guard for the 1003
**Both loan applications in the set failed. 100% of the type.**

The 1003 is read by **28 rules — more than any other document.** Document 205 alone lost ~90 fields including
full employment history and a 5-row liabilities list.

**Add a regression test that a full multi-section URLA extracts.** Not just a fix — a guard, so this cannot
silently return.

---

## PHASE 3 — Extraction-side retry _(independent; can ship first)_

**Appraisal 272 failed with `RateLimitError`** — the call never completed. `rate_limited: true` was recorded.

**LP-462 added backoff retry to classification. Extraction needs the same.** This is the one item here that
needs no diagnosis, and it recovers a Form 1073 condo appraisal (appraiser, $296,000 value, 3 comps, HOA
$136/mo, condition C3).

---

## PHASE 4 — Re-extract, highest value first

1. **URLA 205, 206** — the 1003 is read by 28 rules
2. **Leases 174, 175, 176** — full standard-form leases with terms, parties and rent
3. **investment_account 257** — `security_positions` empty (0 of 27 rows); *"the schema is well-designed and
   the free reader read everything — a clean extractor bug"*
4. **homeowners_insurance 103, property_profile 198, appraisal 272**

### ⚠️ One document needs two fixes
**261** is an **ALTA Settlement Statement** (sale $446,035, loan $437,955, ~140 readable fields) that failed
with `ValueError` **and** was classified `miscellaneous_document` at 0.75 — the wrong schema.

**Fixing the crash alone would extract it against the wrong schema.**
⚠️ **But LP-463 may have already changed this** — with declining now legitimate, a forced 0.75 pick may
resolve differently. **Re-classify it before assuming it needs a cue.**

---

## Order

**Phase 3 first if you want a quick win** — it is independent and needs no diagnosis.
**Otherwise Phase 1 → 2 → 4**, because everything else depends on knowing the cause.

**⚠️ Do not skip Phase 1.** The length correlation is suggestive and confounded; 174 already looks like a
different problem wearing the same error.
