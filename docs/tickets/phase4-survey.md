# Phase 4 readiness survey — what exists before we design the communication module

- **Type:** Read-only survey. Nothing built, nothing changed, no model calls, no bench run.
- **Date:** 2026-09-05
- **Branch:** `bedrock_integration_with_rules_staging` (the request named `phase3_bucket_2_fast`;
  this is read-only so the branch was not switched — flagged rather than silently ignored).
- **Source for Phase 4's assumptions:** `docs/domain/V1_Build_Plan_v3_rule_engine.docx`, paras
  853–917 (Phase 4) and 918+ (Phase 4.5, condition management).

## What Phase 4 assumes, verbatim from the plan

> **4.1** "When processor clicks 'Request docs' on a finding, the request is added to pending
> draft" · "Multiple requests accumulate into one email"
>
> **4.2** "Each file gets a dedicated email address… Address format: `lf-{token}@app-domain`" ·
> "SendGrid Inbound Parse or AWS SES inbound parsing" · "Email body saved to communications table"
>
> **4.3** "Timeline of sent emails, received emails, drafts, activity events"
>
> **4.4** "sister works directly with underwriters, not Account Executives" · "Per-lender contact
> configuration (underwriter email, portal URL)"
>
> **Depends on:** "Phase 3 (findings to request) and Phase 1.5 (borrower contact from MISMO)"

The load-bearing assumption is **finding → request → draft**, one finding at a time, human-initiated.

## 0. Where these numbers come from, and what they are not

**Staging is stopped.** `./scripts/deploy staging query` returns `STOPPED staging is shut down`
(the LP-630 overnight shutdown). Bringing it up costs money and changes state, which contradicts
this survey's own "$0, change nothing" constraint, so it was not done.

Everything numeric below is therefore from the **local dev database**, which holds 30 loan files,
428 findings (106 live, 322 retired), 337 needs items and 111 documents. That is seed and test
data, not the real files. The identities in it (Akash / Bansari Patel) are invented fixtures.

**What this means for the report.** The *structural* questions — §2's chain, §3's needs layer,
§4's scaffolding, §5's audience, §6's composer — are answered from the code and are exact. The
*volume* questions (§1 counts, §7) are answered from seed data and should be re-run against
staging before any Phase 4 sizing decision. The ticket's own reference points ("132 findings
before LP-509 and 30 after", "one unidentified document cost 22 queue rows") are staging numbers
and are cited where relevant.

## 1. What a real file's findings look like

### Verdict distribution — all live findings (local)

| origin | evaluation_outcome | n |
|---|---|---|
| `deterministic_rule` | `(null)` | 24 |
| `deterministic_rule` | `satisfied` | 18 |
| `deterministic_rule` | `couldnt_check` | 14 |
| `deterministic_rule` | `needs_review` | 6 |
| `deterministic_rule` | `open` | 4 |
| `ai_cross_source` | `(null)` | 40 |

**Two finding systems coexist and are not interchangeable.** 40 of 106 live findings come from the
legacy AI cross-source sweep and carry **no `evaluation_outcome` at all**. The schema layer keeps
them as a deliberately distinct type — `FindingPublic` vs `RuleFindingPublic` — with the comment:

> "Keeping them two DIFFERENT types is the structural guarantee that the two systems' findings
> cannot be concatenated"

No `fired` or `pending_automation` rows exist in this data. `status` (the colour axis) is separate:
84 yellow, 18 green, 4 red.

### Distinct rules vs distinct (rule, subject)

| file | findings | non-satisfied | distinct rules | distinct (rule, subject) |
|---|---|---|---|---|
| LF-6T3N | 55 | 37 | **18** | **45** |
| LF-96SV | 20 | 20 | 8 | 8 |
| LF-XKQ3 | 17 | 17 | 8 | 8 |
| LF-F4T7 | 12 | 12 | 8 | 8 |
| LF-RM6U | 2 | 2 | 2 | 2 |

**The fan-out is real and it is uneven.** On LF-6T3N, 18 rules produce 45 subject rows — the "a rule
firing on 10 deposits is one problem, not ten" concern is confirmed. On the other four files the two
counts are identical, so the fan-out is a property of *which rules fire*, not of every file.

### Ratification

`details` contains no `ratification_pending` key on any of the 106 live findings (0/106). The
ratification signal is carried **in the message text instead** — every judgmental verdict ends
with the literal suffix:

> `— 'yes' is an AI judgment and must be ratified by a human`

That is a string, not a field. Anything wanting to count or filter ratification-pending findings
today would have to match on that sentence.

## 2. The `couldnt_check` question

14 live `couldnt_check` findings. They fall into **three shapes, and only one of them is a document
request.** This is the central finding of the survey.

### Shape A — "the document is missing, and here is its type" (1 of 14)

```
file=LF-96SV  rule=ID-7  subject=missing:title_commitment
message: no 'title_commitment' document in the file — the rule requires one to
         evaluate (the document is expected but missing; lost visibility, not out of scope)
```

The document type is in the message **and in the subject key**, as the literal convention
`missing:<document_type>`. This one is a document request already.

### Shape B — "a document is here but we don't know what it is" (8 of 14)

```
file=LF-6T3N  rule=ID-7  subject=docb60ccc7adcda9ceb
message: applicability tag 'document.document_type' is unknown — cannot confirm the rule applies

file=LF-6T3N  rule=ID-9  subject=docf643a47d20d8296f
message: applicability tag 'document.document_type' is unknown — cannot confirm the rule applies
```

**Eight of fourteen — the largest group — are not requests at all.** The document is already in the
file; the classifier could not type it. Asking a borrower for it would be wrong. Four unidentified
documents × two rules (ID-7, ID-9) produced these eight rows. This is the LP-636/637/638 territory
(re-classification), not Phase 4's.

The engine already knows the difference. `RuleEvaluation` carries a dedicated flag, LP-640:

> "this abstention is 'we do not know what that document IS', not 'we looked and the fact is
> missing'. Set only on a COULDNT_CHECK whose applicability abstained on the DOCUMENT-TYPE
> predicate… ONE unidentified file cost 22 queue rows on LF-ZE9N"

### Shape C — "only one source; nothing to compare" (5 of 14)

```
rule=ID-2  message: only 1 source(s) carry 'id.ssn_hash' for this subject — nothing to
                    compare across sources
rule=ID-3  message: only 1 source(s) carry 'id.dob' for this subject — nothing to compare
                    across sources
rule=ID-4  message: only 1 source(s) carry 'id.address_normalized' of type 'residence' for
                    this subject — nothing to compare across sources (1 other source could
                    not be typed as 'residence' and was excluded from the compare)
```

A real request — for *one more* source — but **no document type is named**, because any of several
would do.

### Does a finding record WHICH document would resolve it?

**Yes, through a three-step fallback that already exists.** The chain is resolvable programmatically
today. It was built for exactly this question (LP-541, LP-620, LP-640):

1. **`requires_documents` on the rule spec** — `67 of 78` active rules carry it. Each entry is a
   group of ALTERNATIVES; a group is satisfied if the file holds any member, and every group must be
   satisfied. `_missing_documents()` in `app/schemas/verification.py:300` resolves it, labelling each
   gap with the group's first member:

   > "The label is the group's FIRST member: the canonical form the processor should ask for, where
   > the rest are the substitutes we would also accept."

   The validator rejects a spec naming a type the catalog does not carry
   (`specs.py:1129`), so the mapping cannot drift from the document catalog.

2. **`requested_documents` on the finding** — where the spec cannot answer. LP-620's own comment
   names Shape C as the reason it exists:

   > "`requires_documents` is a per-RULE presence test… That cannot express 'one MORE source than
   > the file already has', which is exactly the consistency engine's single-source abstention —
   > ID-3 gathers a date of birth from one document, needs two to compare, and computes 'nothing
   > missing' because a driver's licence IS on file."

3. **`undetermined_by_document_type`** — LP-640's flag, which marks Shape B so it is *not* treated
   as a request.

**Where it breaks.** The 11 active rules with no `requires_documents` are
`DT-8, ID-1, ID-2, ID-3, ID-4, IN-13, IN-5, OC-1, OC-2, PE-1, PE-3` — and **ID-2, ID-3 and ID-4 are
precisely the rules that produce Shape C**. For those, resolution depends entirely on the evaluator
having set `requested_documents` per subject; the spec-derived path returns nothing.

### How many findings trace to the same missing document?

Locally: 8 findings from 4 unidentified documents across 2 rules. The repo's own staging measurement
is stronger and is recorded in `result.py`: **one unidentified document cost 22 queue rows on
LF-ZE9N.** Consolidation is already built for that case (LP-640, `1c3c197`).

## 3. Does a needs-list layer already exist?

**Yes, and it is substantial.** `needs_items` — `app/models/needs_item.py`, 337 live rows locally.
This is not scaffolding; it is a working layer with its own engine (`services/needs_engine.py`,
~1,200 lines), prose composer (`services/needs_prose.py`), API and frontend.

### How a requirement is created — five origins, all populated

| origin | rows | what it is |
|---|---|---|
| `ai_reasoning` | 201 | LP-69's reasoner proposes needs from the file |
| `floor` | 79 | `seed_floor_needs()` — deterministic universals + purpose/occupancy branches |
| `template` | 36 | earlier-defined origin |
| `manual` | 9 | processor-authored |
| `finding` | 1 | `seed_needs_from_findings()` — **findings already become needs** |

`finding` is the origin Phase 4 assumes a human creates by hand. It exists
(`services/needs_from_findings.py`) and is wired into the verification run.

Status: `pending=282, verified=25, received=12, waived=4, rejected=3`.
Disposition: `proposed=186, confirmed=137, waived=3` — a proposed/confirmed axis separate from status.

### How a requirement is satisfied — **by document type label alone**

Stated explicitly, as the survey asks. From `needs_engine.py:9`:

> "pending need (TYPE-LEVEL: a need for `needs_type == document_type`)"

Satisfaction compares the **stored type label** against the **classifier's label**. It does not read
extraction substance, and it does not read tier. Three widenings exist — umbrella categories
(`asset_statement`, `income_document` match any document in a category), named alternatives
(`government_id` matches any of five ID types), and aliases (`verification_of_employment` → `voe`) —
but all three are still label comparisons.

**A misclassified document therefore closes a requirement it should not.** This is not hypothetical:
it was observed on LF-ZE9N this session — a credit-report *invoice* classified as `credit_report`
flipped the need to `received`, while three rules correctly reported no credit report because they
need tradelines and found none. The needs list and the rule engine disagreed about the same file, and
the needs list was wrong.

The repo carries the inverse defect too, recorded as bug-001/bug-009: a `needs_type` no document can
carry sits on the list forever, unclearable by the very upload it asks for.

## 4. Communication scaffolding already in the repo

### What exists

| thing | state |
|---|---|
| `communications` table | **exists**, full shape — direction, channel, status, sender, recipient, subject, body, `needs_item_id`, `initiated_by_user_id`, `external_message_id`, `sent_at`, `error_detail` |
| `create_communication()` | **exists**, `services/communications.py` |
| `loan_files.inbox_token` | **exists**, and is populated on **all 30** local files |
| `lenders.contact_email` / `.portal_url` / `.contact_phone` | **exist** |
| `activity_logs` | **exists**, 282 rows, 29 event types |

### What does not exist

- **No caller of `create_communication`.** Zero. The `communications` table has **0 rows**.
- **No API endpoint** touching `Communication` anywhere in `app/api/`.
- **No outbound email capability of any kind** — no SendGrid, no SES, no SMTP client, no
  transactional templates. The service's own docstring says so:

  > "Communication service — minimal record creation (**sending is Phase 4, LP-20**)."
  > "Just persists the message state — actually sending an email (outbound) and routing an inbound
  > one are Phase 4."

- **No inbound handling** — no webhook endpoint, no parser. `inbox_token` is a column with no reader.
- **No template, draft or thread model.**
- **A `/communication` route exists and is a placeholder.**
  `frontend/app/(protected)/loan-files/[id]/communication/page.tsx` renders `<TabPlaceholder
  title="Communication" phase="Phase 4" …>` and nothing else. The tab is in the file's navigation
  already, so a processor can reach it today and finds a stub. No compose, draft, thread or message
  view exists behind it.

So the persistence shell for Phase 4.1–4.3 is built and completely unused; the transport, the
templates and the UI are absent.

### The activity log as a timeline source

29 event types, including the ones Phase 4.3 names: `document_uploaded`, `document_processed`,
`document_reprocessed`, `verification_run`, `status_changed`, `needs_item_created`,
`needs_item_satisfied`, `communication_sent`, `communication_received`, `note_added`.

`communication_sent` and `communication_received` are **already in the enum** and are never emitted —
nothing calls them, because nothing sends or receives. The timeline's event vocabulary is ready.

## 5. Who each finding is FOR

### Nothing indicates audience. Anywhere.

The rule specs' complete top-level vocabulary, across all 84 files, is 19 keys:

```
rule_id, name, category, kind, numeric_check, criteria, applicability, required_inputs,
reference_values, subject_enumeration, subject_key_fields, evidence_required,
guideline_reference, spec_version, requires_documents, deterministic, judgment,
consistency, collapse_uniform
```

**None of them names a party.** No `audience`, no `resolved_by`, no `owner`, no `actor`. The
`category` field is the rule's *domain* (Income, Assets, Credit, Title…), not who fixes it. The
finding row carries no such field either, and the document catalog's `DocumentCategory` is a
subject-matter axis too.

There is no convention standing in for one — the survey asked whether a field, a category *or a
convention* exists, and the answer to all three is no.

### Could it be derived from the document type?

Partially, and the mapping does not exist. The catalog's 166 types across 7 categories:

| category | types |
|---|---|
| `income_employment` | 40 |
| `property` | 36 |
| `borrower_info` | 25 |
| `assets` | 20 |
| `disclosures` | 17 |
| `credit` | 15 |
| `misc` | 13 |

A derivation would need a **document-type → responsible-party** table authored per type, not per
category, because the category axis cuts across parties: `credit` holds both the credit report (the
processor orders it from a vendor) and a credit explanation letter (the borrower writes it);
`property` holds the appraisal (ordered), the purchase agreement (borrower/agent) and the title
commitment (title company). Category alone would route a third of these wrongly.

It would also only cover Shape A and Shape C findings — Shape B (an unidentified document, the
largest group) has no document type by definition, which is what makes it Shape B.

### Per-lender contact configuration — already exists

Phase 4.4 asks for "Per-lender contact configuration (underwriter email, portal URL)". The `lenders`
table already carries `contact_email`, `portal_url` and `contact_phone`. What does not exist is any
notion of **which underwriter is working a specific file** (Phase 4.4's fourth bullet) — there is no
per-file underwriter assignment anywhere.

## 6. The finding's own text

### What produces it

`services/finding_prose.py` (LP-527) — a composition **pass that runs after the findings are
written**:

> "It reads them, asks a model to rewrite the text of each, and writes back only `message` and
> `how_to_fix`. Nothing else is touched: not the verdict, not the outcome, not the tags, not the
> reconcile identity. A total failure of this pass leaves a fully correct run whose findings read
> exactly as the templates wrote them."

Per finding, not batched, with a fact-keyed cache.

### Is a fix carried separately from the reason? Yes.

`how_to_fix` is a distinct field on `RuleEvaluation` and on the public schema, populated from the
rule spec's `guidance.how_to_fix`. In the local data it is **null on every rule-engine finding**,
because these rows predate the composer running.

### Is the text written for a processor or a borrower?

**For a processor, and three of the four shapes could not be shown to a borrower as-is.** Verbatim:

```
[OC-2 / needs_review]
The stated occupancy is PRIMARY (occupancy.stated). The tag
occupancy.consistent_with_signals explicitly confirms 'yes' with 0.95 confidence, noting
that the borrower's intent-to-occupy declaration is 'Yes', the FHA secondary residence
indicator is absent (consistent with primary residence), and the property has 1 financed
unit (typical for primary residences). All occupancy signals align with and support the
stated primary residence claim. No contradictory evidence is present in the tags provided.
— 'yes' is an AI judgment and must be ratified by a human
```

```
[ID-2 / couldnt_check]
only 1 source(s) carry 'id.ssn_hash' for this subject — nothing to compare across sources
```

```
[xsrc.identity.name_consistency]
Borrower name differs across sources: AKASH PATEL (pay_stub); AKASH PATEL (pay_stub);
AKASH PATEL (w2); AKASH V PATEL (w2); AKASH VIJAY PATEL (drivers_license); Akash Patel
(application); BANSARI NAGESH PATEL (drivers_license); Bansari N Patel (w2); …
```

(Those names are the invented LF-6T3N fixtures, not real borrowers.)

The first names internal tags and confidences and ends with an instruction to a human reviewer. The
second names a tag id. The third is a raw diff across twelve source rows. Only Shape A —
*"no 'title_commitment' document in the file"* — reads as something a person outside the system
could act on, and even that says "the rule requires one to evaluate".

## 7. Volume reality check

**Local seed data only — re-run against staging before sizing anything.**

Non-satisfied rule-engine findings per file, across the 5 files that have any:

| | |
|---|---|
| mean | 9.6 |
| median | 6.0 |
| max | 29 |

The ticket's own staging reference points are larger and are the ones to trust: **132 findings on
one file before LP-509, 30 after**, and **22 queue rows from a single unidentified document**.

### How much of the list is "the rule is judgmental" rather than "something is wrong"

Of the 78 active rules, by `kind`:

| kind | rules | ratifies unconditionally? |
|---|---|---|
| `structural` | 42 | no |
| `judgmental` | **19** | **yes — every AI verdict is ratification-pending** |
| `calculative` | 17 | no |

The 19: `AS-12, CR-10, CR-8, DT-7, FR-3, FR-5, ID-8, ID-9, IN-13, IN-14, IN-7, OC-2, OC-3, PC-8,
PR-3, PR-4, PR-5, TI-2, TI-6`.

Every verdict from those 19 arrives `needs_review` **by construction, not because anything is
wrong** — Phase 3's own checklist requires it ("Every AI-produced verdict arrives
ratification-pending, and no rule ships auto on an unmeasured tag"), and the plan records it as a
deliberate cost: "Ratification is the safety substitute for a tag whose accuracy has not been
measured, and removing it spends real safety."

In the local data all 6 `needs_review` rows come from 3 judgmental rules (AS-1, ID-8, OC-2 — two
each). **The two OC-2 examples quoted in §6 both conclude that everything is consistent and correct**,
and still require a human. That is the distinction the survey asked about, and on this data it is
the whole of the `needs_review` list.

## Summary of what exists vs what Phase 4 assumes

| Phase 4 assumption | reality |
|---|---|
| 4.1 "processor clicks 'Request docs' on a finding" | The finding→need path already exists (`needs_from_findings`, origin `finding`). No draft accumulation, no template library, no generator. |
| 4.1 "Multiple requests accumulate into one email" | Nothing accumulates. No draft model. |
| 4.2 per-file address `lf-{token}@…` | `loan_files.inbox_token` **exists and is populated**. No address derivation, no inbound route, no parser. |
| 4.2 "Email body saved to communications table" | Table **exists**, 0 rows, 0 callers. |
| 4.3 timeline of sent/received/drafts/activity | `activity_logs` has the vocabulary including `communication_sent`/`communication_received`; both are **never emitted** (verified: no reference outside the enum). A `/communication` tab exists as a `TabPlaceholder` stub. |
| 4.4 per-lender contact config | `lenders.contact_email` / `.portal_url` / `.contact_phone` **exist**. No per-file underwriter assignment. |
| 4.5 reminder automation | Needs carry `status` and timestamps; nothing computes overdue. |
| "Depends on Phase 3 (findings to request)" | The dependency is met further than the plan assumes: findings already become needs, and 67/78 rules already declare which documents would resolve them. |

## Where a chain breaks, stated plainly

1. **Shape B is the largest `couldnt_check` group and is not a request.** 8 of 14 locally, 22 rows
   from one document on staging. Any finding→request path that does not read
   `undetermined_by_document_type` will ask a borrower for documents already in the file.
2. **ID-2, ID-3, ID-4 have no `requires_documents`** and are exactly the rules producing the
   "one more source" abstention. Their resolution depends on the evaluator having set
   `requested_documents` per subject; there is no spec-derived fallback for them.
3. **Needs satisfaction is by type label alone**, so a misclassified document closes a requirement.
   Observed on LF-ZE9N this session.
4. **No audience information exists at any layer.** Deriving it needs a per-document-type
   responsible-party table that has to be authored; the category axis cuts across parties.
5. **`ratification_pending` is a sentence in the message, not a field**, so the judgmental/real
   split cannot be filtered without string matching.
6. **No transport exists.** Not a gap in configuration — there is no email client of any kind in
   the dependency tree.

## How this was checked

Every absence claim here was verified more than one way, because two of them were wrong on the first
pass:

- "No frontend communication view" was written from a filename grep for *model* names
  (compose/draft/message/template). A route directory named `communication` exists and holds a
  placeholder tab — found only on a second search by path rather than by concept. Corrected above.
- "No email capability" was first written from a grep that matched `SES` inside unrelated comments
  in `document_processing.py` and `s3.py`. Re-checked against `pyproject.toml` (only `aioboto3`, for
  S3 and Bedrock credentials) and against the source for an SES client or `send_email` call: none.

Counts come from the local dev database via `sqlalchemy` against `settings.database_url`; rule and
spec counts come from `ACTIVE_RULE_IDS` and the 84 spec YAML files read directly. Staging was not
started, so no staging figure in this report is first-hand — the two that appear (132/30 findings,
22 queue rows) are quoted from LP-509 and `result.py` respectively and are labelled where used.
