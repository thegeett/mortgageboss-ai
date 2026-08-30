# LP-UI-032 — Confidence and provenance

Epic E. Three categorical tiers, no raw decimal in the default view, criticality
overriding confidence, inferred values badged.

## What the corpus says, measured first

Over the 90 current extractions / 734 valued fields in the dev corpus:

| | |
|---|---|
| 190 (25.9%) | carry a per-field `confidence` |
| 544 (74.1%) | have **no `confidence` key at all** |
| 15 of 90 | extractions carry any per-field confidence |

And of the 190 that are rated: median **0.99**, p90 **1.00**, 142 (74.7%) at or
above 0.97 — and **exactly one field in the whole corpus below 0.85**.

Three consequences, and they reshape the ticket rather than decorate it.

## Finding 1 — the 0.85 threshold is inert on today's data

One field out of 734 falls below it. A tier that fires once per corpus is not a
signal a processor can learn to trust. The threshold is implemented as specified
and it is not what makes this screen useful; criticality is.

## Finding 2 — the ticket has three tiers and the data has four

Verified / Confident / Check this has no home for the **74% of fields with no
rating at all**. Rendering those as "Confident — no chrome" would show the
*absence* of a rating as a positive one, which is the same error the ticket exists
to prevent ("a figure that was never read must not look identical to one that
was"), one level up. So there is a fourth tier, **Not rated**, in neutral — not
amber, because three-quarters of every document in warning colours would make the
real warnings invisible.

## Finding 3 — "Verified (human-confirmed)" has no producer and cannot occur

Searched exhaustively: `create_extraction_version` is written by the extraction
task and the seed script, and by nothing else. There is no endpoint, service or
model by which a processor confirms or corrects an extracted field value. The
document-type override (LP-44) is the only human correction in this area and it
corrects the *type*, then re-extracts.

`tierFor` implements the tier — it is a total function and the branch is tested —
but nothing sets `humanConfirmed`, so **no field can reach Verified today**. The
tier is a promise the data cannot keep until a confirm action exists. Recorded in
AMENDMENTS A26.

## Finding 4 — "inferred" does not apply to this pane

An inferred badge needs a value that was derived or carried over rather than read.
Every value in the extracted-fields pane is read off a page or is null; each
carries its own source snippet. Derived values do exist — the rule engine's
`derived` tag producer — but they live in the verification snapshot, not here. The
badge would have nothing to badge. The AC is met in the only place it can be: a
field whose text could not be located says so (LP-UI-031), and a value with no
rating is not passed off as a rated one.

## Finding 5 — the two thresholds and "criticality overrides" contradict each other

The ticket asks for a 0.97 critical threshold **and** for criticality to override
confidence. The second swallows the first: if a critical field is checked whatever
its number, there is no number at which 0.97 decides anything. The AC's explicit
sentence — *"a 0.97 loan amount, note rate, SSN or income figure still gets
flagged"* — is the concrete half, so it wins. `CONFIDENCE_CRITICAL` is kept,
exported and parity-tested against the stylesheet, with the tension written down
at its definition rather than resolved silently by deleting one side.

## What was built

**`backend/app/verification/critical_fields.yaml` + `field_criticality.py`.** 199
field names in eleven reviewed categories, 24 ruled out each with its reason. Data
rather than code, the same posture as `distrusted_fields.yaml`: reviewable and
prunable. Keyed on the field NAME — a money figure is a money figure on whatever
document it appears, and across 121 document types and 1,603 typed-core keys a
per-document list would stop being legible, which is the same as stopping being
reviewed.

**The drift guard is the point.** `test_no_critical_field_drifts` fails when a
schema spec introduces a key of critical shape that is in neither list. A new
extractor cannot quietly add an unclassified money field; the decision is forced
where it is cheap. The shape regex is deliberately wide — a false positive costs
one line with a reason, a false negative is an unflagged money figure.

**`field_scrutiny` on the document detail response** — `{field: {critical,
distrusted_reason, sensitive}}`, only for fields with something to say. An
ordinary field is absent rather than present-and-false, so the payload does not
grow with the spec vocabulary. Resolved in the backend because the critical list
lives beside the schema specs and the distrust list beside the rule engine;
reimplementing either on a screen is how they drift.

**`frontend/lib/confidence.ts`** — `tierFor`, four tiers, and the ordering that
matters: human confirmation, then distrust, then criticality, then the number.
Criticality is read **before** the confidence, so a missing rating cannot buy a
critical field a pass.

**`ScrutinyMark`** — a confident field renders **nothing at all**. `check` is
`attention`, never `blocking`: the field is worth reading, not wrong — if the
system knew it was wrong that would be a finding. The number lives in the hover
beside the reason, and the trigger is keyboard-reachable because the reason is
only in the hover.

## Two problems the screen showed that the tests did not

**`ytd_gross` was not flagged.** My first shape pass missed it — `ytd_gross`
matches no money pattern by name — so the income-averaging basis sat unmarked
beside a flagged gross pay. Caught by looking at a real pay stub. The shape was
widened (`gross`, `hours`, `ytd`, `percent`, `deposit`, ratios) and 52 more fields
classified. This is the exact false negative the ticket exists to prevent, and it
survived a passing test suite.

**`borrower_ssn` rendered an unmasked SSN.** `MASKED_FIELD_KEYS` held two keys —
`employee_ssn` and `account_number_masked` — while the corpus carries
`borrower_ssn`, `co_borrower_ssn`, `spouse_ssn_masked`, `taxpayer_ssn_masked` and
more. On a real credit report the pane would print a live Social Security number.
Fixed by having the backend answer `sensitive` from the same `identity` category —
one list, so an SSN field added to it is masked by construction — with the
frontend's own set kept as a floor, so a backend that stops answering cannot
un-mask something masked today. Out of this ticket's scope and fixed here because
it is a live PII leak on the screen the ticket is about.

Also fixed: a valueless field was marked "Check this", telling a processor to go
and read a dash. The empty-value dash is now a named `EMPTY_VALUE` export rather
than a literal repeated in four places, because it is compared as well as produced.

## Tests

- `tests/verification/test_field_criticality.py` — 35, including the drift guard
  with its own positive control, and the loader's rejections exercised against
  actual malformed YAML rather than only over the shipped file.
- `tests/api/test_documents_endpoints.py::test_field_scrutiny_reaches_the_endpoint`
  — at the API layer, because a guarded helper with unguarded wiring was the last
  review's finding.
- `lib/confidence.test.ts` (14), `scrutiny-mark.test.tsx` (7), masking and
  confidence plumbing in `lib/loan-files/documents.test.ts`.

Mutation-checked, 25 mutations across six files, all caught: the loader returning
nothing, everything critical, a reason no longer required, `gross_pay` dropped, a
field in both lists, the spec directory reading empty, criticality no longer
overriding confidence, an unrated field rendered as confident, the distrust list
ignored, the threshold made exclusive, human confirmation ignored, the TS constant
drifting from the stylesheet, a confident field given chrome, `unrated` coloured
as a warning, `check` escalated to blocking, the mark unreachable by keyboard, the
identifier list ignored, the masking floor removed, an SSN masked to last-4,
confidence fabricated when the model gave none, and four on the scrutiny wiring.

Checked in light and dark, on a pay stub and on a credit report. CI green: biome,
tsc, 786 vitest; ruff, mypy strict, 6129 pytest.

## Open

The critical list is **not domain-expert reviewed** — the ticket asks for that and
it has not happened. The classification is mine, from the field names and the
schema specs, and `reviewed_not_critical` carries a reason for every exclusion
precisely so that review is a reading task rather than an archaeology one.
