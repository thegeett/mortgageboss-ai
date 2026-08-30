# LP-UI-033 — Keyboard review rhythm

Epic E, and the ticket that closes AMENDMENTS A26a: `Enter` accept and `R` reject
are the human-confirmation producer LP-UI-032 found missing, so this is a backend
feature before it is a keyboard layer.

## What it needed that did not exist

LP-UI-032 established that nothing in the codebase let a processor confirm or
correct an extracted field value — `create_extraction_version` is written by the
extraction task and the seed script and by nothing else. `ValidationVerdict`
(LP-89) looks close by name and is not: it records the domain expert's verdict on
*rules and calculator methodologies*, a different subject with a different
lifecycle. So `field_reviews` is new.

## The two decisions in the model

**A verdict sits beside the value, never on top of it.** A correction does not
rewrite `extracted_data`. "What did the model actually say?" is the question every
accuracy investigation starts from — the LP-508 distrust ledger is entirely that
question — and overwriting the value to record the correction destroys the
evidence in order to store the verdict. The display resolves the two; the
extraction is never touched.

**Keyed on the extraction, not the document.** A re-extraction produces a new
version with possibly different values, and a verdict recorded against the old one
must not silently vouch for the new. The `ON DELETE CASCADE` from `extractions`
means a superseded version's reviews go with it and its fields return to
unreviewed. That costs a processor a second pass; the alternative costs an
underwriter a wrong file. Recorded as ADR-393.

Lifecycle is the DTI/LTV/calculator override pattern unchanged (LP-76/77/87): one
live row per (extraction, field) via a partial unique index, soft-delete to
revert, the activity log as the immutable trail.

## What was built

**Backend.** `FieldReview` + `FieldVerdict` (accepted / corrected / rejected), a
hand-written migration that also creates the `readonly.field_reviews` view and
swaps the `activity_type` CHECK for two new values, `services/field_reviews.py`
for the record/replace/revert lifecycle, and three endpoints under the same tenant
gate as the rest of `/documents/{id}`. The verdict travels back on
`field_scrutiny`, beside the criticality LP-UI-032 put there, so one call answers
both.

**The readonly view drops `corrected_value` and `note`** and exposes
`has_corrected_value` / `has_note` instead. A corrected value is by construction
the one place a raw identifier arrives by hand — correct an SSN field and the
correction *is* an SSN — and scrubbing catches only the shapes it knows. What
remains still answers the questions the table exists for: how often fields are
corrected, which get rejected, who reviewed what.

**The corrected value is kept out of the activity log** for the same reason. An
activity log is read widely; the row holds the value.

**Frontend.** `use-review-keys.ts` (the binding table and the input guard, both
pure and testable), `review-queue.ts` (which field the loop stops on),
`shortcut-sheet.tsx` on `?`, `verdict-editor.tsx` for `E` and `R`, and the wiring
in the review route.

## Rules that make the loop honest

- **Shortcuts never fire while a text input has focus.** Not politeness: `R` is a
  rejection and `E` opens an editor, so typing "Rate" into a correction box would
  reject four fields and open the editor twice. Verified live in the browser as
  well as in tests.
- **`Enter` with no field selected does nothing.** "Accept whichever field is
  first" would silently vouch for a value the processor never looked at.
- **A rejection requires a reason**, enforced in the service and in the button.
  Either alone is a suggestion; both together are a rule.
- **A rejection is not confirmation.** "I could not verify this" is the opposite
  of "this is right", so a rejected field keeps its mark and does not read as
  verified.
- **`⌘Enter` only advances when the document is actually fully reviewed.**
- **`nextAttention` returns the current field when it is the only one left**,
  rather than `null`. `null` reads as "nothing left", and a field still wanting a
  decision is the opposite of that; completion has its own answer in
  `isFullyReviewed`.

## The bug the screen found

`Enter` recorded the verdict, the API stored it, the field dropped out of the
keyboard loop — and the mark beside the row went on saying "Check this". Two
computations of one fact: `buildQueue` knew about verdicts and `tierInputFor`,
written in LP-UI-032 before verdicts existed, did not. Both callers now derive the
tier through `tierInputFor`, with a test for the accepted/corrected/rejected
mapping. Found by driving the loop in a browser and reading the marks, not by any
test — every test passed throughout.

Also caught, by an existing guard rather than by me: `text-sm` on the editor's
`Input` and `Textarea` would have triggered iOS auto-zoom on focus.
`form-control-zoom.test.ts` names three previous times that regressed; this would
have been the fourth.

## Tests

- `tests/integration/test_field_reviews.py` — 15, the lifecycle and the two rules.
- `tests/api/test_documents_endpoints.py` — accept/withdraw, a correction leaving
  the extraction intact, a reason-less rejection refused, a verdict on a field the
  extraction lacks refused, and all three routes tenant-scoped.
- `use-review-keys.test.tsx` (29), `review-queue.test.ts` (19),
  `shortcut-sheet.test.tsx` (14).

Mutation-checked, 25 mutations, all caught — including the input guard removed,
`contenteditable` unrecognised, bare `Enter` tested before `⌘Enter`, the loop
stopping on confident fields, a decided field walked onto again, a rejection
counted as confirmation, no wrap, an empty document reported fully reviewed, both
tenant gates, the corrected value written into the activity log, and a replaced
verdict mutated rather than kept.

The sheet is written by hand and `shortcut-sheet.test.tsx` asserts it agrees with
the binding table. Generating it would couple them in the direction that hides a
bug: a binding that silently changed would change the sheet with it and still look
right.

Checked in light and dark, and driven live in the browser. CI green by exit code:
biome, tsc, 858 vitest; ruff, ruff format, mypy strict, 6150 pytest.

## Open

**A correction is recorded and nothing consumes it.** The rule engine reads
`extracted_data`, which a correction deliberately does not touch — so a processor
can fix a wrong gross pay and the DTI will still be computed from the model's
figure. That is the honest state today and it is not a small gap: it is the
difference between a correction being a note and a correction being a fix. Making
the engine prefer a corrected value is a verification-layer decision with its own
consequences (does a correction re-trigger a run, does it invalidate findings that
cited the old value), and it is recorded in AMENDMENTS A28 rather than decided
here.

---

## Review (LP-UI-033 review commit)

Reviewed on request from the session running the epic. Five findings, recorded in
full as AMENDMENTS A30. The open item the ticket named first was the right one to
attack, and the answer was not the one it expected.

### 1. The cascade the ADR relies on never fires

ADR-393 and the migration both said a superseded extraction's verdicts go with it
via `ON DELETE CASCADE`. Re-extraction deletes nothing:
`create_extraction_version` demotes the current row and inserts a new one, prior
versions are kept for audit, and no code path deletes an `Extraction`.

The behaviour is still correct — a verdict is keyed on `extraction_id`, so a new
version has none — but the mechanism is the key, not the cascade. A cascade
guarantees something about *deletion*; a key guarantees something about
*identity*. Change re-extraction to update in place and every verdict would follow
values nobody reviewed, with the cascade powerless. `TestReExtraction` pins the
new version unreviewed, the old version's verdict surviving as history, and the
cascade working on an actual delete. ADR-393 and the migration docstring corrected.

### 2. A rejection rendered as nothing

`tierInputFor` sets `humanConfirmed: false` for a rejection — right — under a
comment saying a rejection "must keep its mark". It kept none: `false` returns the
field to the ordinary path, where a non-critical field rated above the standard
threshold is `confident`, which renders `null`. A processor could reject a value
and watch their decision vanish from the row. Added a `rejected` tier toned
`blocking`: `check` means the system does not know, a rejection means a person does.

### 3. The input guard could not cover the editor's buttons

`isTypingTarget` correctly excludes only text-entry elements, and a `<button>` is
not one. But the verdict editor is inline and the listener stayed live behind it,
so `Enter` on Cancel activated the button *and* fired `accept` — an acceptance
recorded on the field someone had opened to reject. `Tab` was quieter and worse:
the hook `preventDefault`s it, so a keyboard user could not reach Save. The
shortcut sheet was already handled; the editor was missed because it is not a
dialog. `shortcutsEnabled({ helpOpen, editing })` states the rule once, as a named
predicate so it can be tested.

### 4. The readonly drift guard passed on a substring

`(corrected_value IS NOT NULL) AS has_corrected_value` contains the string
`corrected_value`, so a `\bname\b` search called the column exposed while the view
exposes only a boolean — and the deliberate drop went unrecorded in `EXCLUDED`.
The guard now reduces each select item to the name it comes out as. Tightening it
surfaced exactly these two columns and no others.

### 5. `is_sensitive` still was not asking the list that knew

A29's finding, confirmed: `_PII_FIELDS` classifies 83 field names by `PiiKind` and
`is_sensitive` consulted only the 27 in `critical.identity`. Among the 56 it
skipped were `aba_routing_number` and `account_number`, both rendering in the
clear. `is_sensitive` answers from both lists now, defaulting to MASK.

The correction needs care in the other direction too: `_PII_FIELDS` has only two
kinds, `ssn` and `account`, and `account` holds `aba_routing_number` and
`loan_number` alike. A first pass masked the loan number, which a processor reads
on every document. Two written exception lists now answer two different questions
— `critical.identity_readable` (critical and shown: a DOB, an EIN, a licence) and
top-level `pii_readable` (shown, not critical: a loan number, a policy number) —
with a test locking the escape hatch so an account or routing number cannot be
argued onto the readable side.

This is my own A27 fix being narrower than what already existed — I authored a
list beside a registry instead of deriving from it. Worth stating plainly, because
it is the second time in two tickets that the masking bug was not "nobody knew"
but "the code that decides was not asking the code that knew".

### Confirmed, not changed

- The shortcut sheet's dialog path was already handled with `!helpOpen`.
- `tierInputFor` is genuinely the single tier derivation; nothing else in the tree
  computes a tier or a verdict-ish fact independently.
- The readonly view for `field_reviews` is correctly registered and seen by
  `test_every_table_has_a_view_or_is_excluded` — verified by evaluating the guard's
  own table and view maps, not by the suite passing.

### Verification

Frontend: biome 0, tsc 0, **869 vitest**, build clean. Backend: ruff 0, format 0,
mypy strict 0, **6,156 pytest**. Ten mutations run, all caught.
