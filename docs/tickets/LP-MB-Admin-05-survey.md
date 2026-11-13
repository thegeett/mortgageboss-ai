# LP-MB-Admin-05 — Part 2 survey: every read of a loan file

Date: 2026-11-13

Enforced by LP-MB-Admin-06; `tests/api/file_doors.py` is now the list of record.

This lists every API route in `backend/app/api/*.py` and every Celery task in `backend/app/tasks/*.py` that
reaches a loan file or one of its children, grouped by how it gets there, so that Part 2 ("restrict
files to their team") can be enforced at every door before any enforcement code is written. Group C is
where a restricted file would leak, and is listed first.

All paths include the `/api/v1` mount prefix from `app/main.py:65` plus the router's own prefix. All
`file:line` references are relative to `backend/` and point at the route decorator or the task decorator.

## Counts

| Group | What | Count |
|---|---|---|
| A | Routes through `ScopedLoanFile` / `get_scoped_loan_file` | 64 |
| B | Routes that call `get_loan_file` / `list_loan_files` / `count_loan_files` directly, including through the conditions router's own `ScopedLoanFileById` dependency | 69 |
| C | Routes that reach a file through a child id, a token, or a company-wide query | 68 |
| D | Celery tasks and beat jobs that read a file or its children | 16 |
| **Total** | | **217** |

Of the 253 route decorators in `app/api/*.py`, 64 + 69 + 68 = 201 are listed here; the other 52 are in
"Not file reads" below. Celery registers 21 tasks; 16 are listed, 5 are excluded below.

**Measured against the ticket.** The ticket says `get_scoped_loan_file` has "98 uses, one fix covers
them". Measured: 64 routes declare `ScopedLoanFile`. A further 29 routes (all in `api/conditions.py`)
declare `ScopedLoanFileById` (`api/conditions.py:411`), a separate dependency that calls `get_loan_file`
itself. A fix only in `get_scoped_loan_file` would miss those 29; they are in group B for that reason.

---

## Group C — reached by a child id, a token, or a company-wide query (the risk)

Each of these is tenant-checked today (company only), but none passes through `ScopedLoanFile`, so a
team check there would not cover them.

### C1. Condition rounds by id — `ScopedRound` (`api/conditions.py:347`, filters `ConditionRound.company_id`)

One enforcement point covers all 15: add a team check on `round_.loan_file_id` in `get_scoped_round`.

| Route | file:line | How it reaches the file | Enforcement point | Risk if missed |
|---|---|---|---|---|
| GET /api/v1/condition-rounds/{round_id}/plan | api/conditions.py:578 | round id, company-scoped | team check in `get_scoped_round` | reads a restricted file's round plan |
| POST /api/v1/condition-rounds/{round_id}/plan/confirm | api/conditions.py:585 | round id | team check in `get_scoped_round` | confirms a plan on a restricted file |
| GET /api/v1/condition-rounds/{round_id} | api/conditions.py:613 | round id; then `appearances_for_file(round_.loan_file_id)` | team check in `get_scoped_round` | opens a restricted file's round and its conditions |
| POST /api/v1/condition-rounds/{round_id}/attach-pdf | api/conditions.py:969 | round id | team check in `get_scoped_round` | attaches a PDF to a restricted file's round |
| GET /api/v1/condition-rounds/{round_id}/reading | api/conditions.py:1064 | round id | team check in `get_scoped_round` | reads a restricted file's reading state |
| POST /api/v1/condition-rounds/{round_id}/read | api/conditions.py:1072 | round id; locks `round_.loan_file_id` | team check in `get_scoped_round` | starts AI reading on a restricted file |
| GET /api/v1/condition-rounds/{round_id}/wrong-file | api/conditions.py:1125 | round id; compares to the file's borrower surnames and loan numbers | team check in `get_scoped_round` | shows a restricted file's borrower surnames |
| POST /api/v1/condition-rounds/{round_id}/import | api/conditions.py:1138 | round id | team check in `get_scoped_round` | imports conditions into a restricted file |
| POST /api/v1/condition-rounds/{round_id}/discard | api/conditions.py:1212 | round id | team check in `get_scoped_round` | discards a restricted file's round |
| GET /api/v1/condition-rounds/{round_id}/events | api/conditions.py:1239 | round id | team check in `get_scoped_round` | reads a restricted file's round history |
| POST /api/v1/condition-rounds/{round_id}/reparse | api/conditions.py:1267 | round id | team check in `get_scoped_round` | reparses a restricted file's round |
| PUT /api/v1/condition-rounds/{round_id}/draft | api/conditions.py:1308 | round id | team check in `get_scoped_round` | edits a restricted file's round draft |
| POST /api/v1/condition-rounds/{round_id}/confirm-cleared | api/conditions.py:1341 | round id | team check in `get_scoped_round` | clears conditions on a restricted file |
| POST /api/v1/condition-rounds/{round_id}/reworded | api/conditions.py:1385 | round id | team check in `get_scoped_round` | edits a restricted file's conditions |
| PUT /api/v1/condition-rounds/{round_id}/completeness | api/conditions.py:1422 | round id | team check in `get_scoped_round` | edits a restricted file's round |

### C2. Conditions by id — `ScopedCondition` (`api/conditions.py:376`, filters `Condition.company_id`)

One enforcement point covers all 24: add a team check on `condition.loan_file_id` in `get_scoped_condition`.

| Route | file:line | How it reaches the file | Enforcement point | Risk if missed |
|---|---|---|---|---|
| PUT /api/v1/conditions/{condition_id}/next-step | api/conditions.py:1713 | condition id, company-scoped | team check in `get_scoped_condition` | edits a restricted file's condition |
| PUT /api/v1/conditions/{condition_id}/route | api/conditions.py:1728 | condition id | team check in `get_scoped_condition` | edits a restricted file's condition |
| GET /api/v1/conditions/{condition_id}/items/{item_id}/link-candidates | api/conditions.py:1745 | condition id; item via `_scoped_item` (1698) | team check in `get_scoped_condition` | lists a restricted file's documents |
| POST /api/v1/conditions/{condition_id}/items/{item_id}/links | api/conditions.py:1761 | condition id; `link_document` uses the condition's `loan_file_id` | team check in `get_scoped_condition` | links a restricted file's document |
| DELETE /api/v1/conditions/{condition_id}/items/{item_id}/links/{document_id} | api/conditions.py:1795 | condition id | team check in `get_scoped_condition` | unlinks on a restricted file |
| POST /api/v1/conditions/{condition_id}/items | api/conditions.py:1823 | condition id | team check in `get_scoped_condition` | edits a restricted file's condition |
| POST /api/v1/conditions/{condition_id}/calls | api/conditions.py:1848 | condition id | team check in `get_scoped_condition` | logs a call on a restricted file |
| PATCH /api/v1/conditions/{condition_id}/items/{item_id} | api/conditions.py:1874 | condition id | team check in `get_scoped_condition` | edits a restricted file's condition item |
| DELETE /api/v1/conditions/{condition_id}/items/{item_id} | api/conditions.py:1902 | condition id | team check in `get_scoped_condition` | removes a restricted file's condition item |
| POST /api/v1/conditions/{condition_id}/reading/confirm | api/conditions.py:1911 | condition id | team check in `get_scoped_condition` | edits a restricted file's condition |
| POST /api/v1/conditions/{condition_id}/reading/library-default | api/conditions.py:1938 | condition id | team check in `get_scoped_condition` | edits a restricted file's condition |
| POST /api/v1/conditions/{condition_id}/plan/revert | api/conditions.py:1955 | condition id | team check in `get_scoped_condition` | edits a restricted file's condition plan |
| POST /api/v1/conditions/{condition_id}/plan/describe | api/conditions.py:1966 | condition id | team check in `get_scoped_condition` | reads a restricted file's condition steps |
| POST /api/v1/conditions/{condition_id}/plan/own-way | api/conditions.py:2023 | condition id | team check in `get_scoped_condition` | edits a restricted file's condition plan |
| POST /api/v1/conditions/{condition_id}/prep-status | api/conditions.py:2035 | condition id | team check in `get_scoped_condition` | moves a restricted file's condition |
| POST /api/v1/conditions/{condition_id}/verdict | api/conditions.py:2055 | condition id | team check in `get_scoped_condition` | records a verdict on a restricted file |
| POST /api/v1/conditions/{condition_id}/reopen | api/conditions.py:2077 | condition id | team check in `get_scoped_condition` | reopens a restricted file's condition |
| PUT /api/v1/conditions/{condition_id}/owner | api/conditions.py:2096 | condition id | team check in `get_scoped_condition` | reassigns a restricted file's condition |
| GET /api/v1/conditions/{condition_id} | api/conditions.py:2162 | condition id; then `db.get(LoanFile, …)` in `_route_lenders` (722), items, evidence | team check in `get_scoped_condition` | opens a restricted file's condition by id, with evidence |
| GET /api/v1/conditions/{condition_id}/events | api/conditions.py:2232 | condition id | team check in `get_scoped_condition` | reads a restricted file's condition history |
| POST /api/v1/conditions/{condition_id}/evidence/{evidence_id}/accept | api/conditions.py:2467 | condition id | team check in `get_scoped_condition` | accepts evidence on a restricted file |
| POST /api/v1/conditions/{condition_id}/evidence/{evidence_id}/reask | api/conditions.py:2491 | condition id | team check in `get_scoped_condition` | re-asks on a restricted file |
| POST /api/v1/conditions/{condition_id}/evidence/{evidence_id}/finding | api/conditions.py:2507 | condition id | team check in `get_scoped_condition` | answers a finding on a restricted file |
| POST /api/v1/conditions/{condition_id}/withdraw | api/conditions.py:2707 | condition id | team check in `get_scoped_condition` | withdraws a restricted file's condition |

### C3. Documents by id — `get_document_for_company` (`services/documents.py:206`, joins `Document → LoanFile`, filters `LoanFile.company_id`)

One enforcement point covers all 13 (and the dev route in C6): a team filter in `get_document_for_company`, which needs
the actor passed in (it takes only `company_id` today).

| Route | file:line | How it reaches the file | Enforcement point | Risk if missed |
|---|---|---|---|---|
| GET /api/v1/documents/{document_id} | api/documents.py:608 | document id → file company | team join in `get_document_for_company` | opens a restricted file's document and extraction |
| GET /api/v1/documents/{document_id}/versions | api/documents.py:621 | document id; then its version group | team join in `get_document_for_company` | lists a restricted file's document versions |
| PATCH /api/v1/documents/{document_id} | api/documents.py:635 | document id | team join in `get_document_for_company` | retypes a restricted file's document |
| POST /api/v1/documents/{document_id}/reprocess | api/documents.py:714 | document id | team join in `get_document_for_company` | reprocesses a restricted file's document |
| POST /api/v1/documents/{document_id}/replace | api/documents.py:858 | document id | team join in `get_document_for_company` | replaces a restricted file's document |
| POST /api/v1/documents/{document_id}/resolve-staleness | api/documents.py:934 | document id | team join in `get_document_for_company` | edits a restricted file's document |
| GET /api/v1/documents/{document_id}/reviews | api/documents.py:1025 | document id | team join in `get_document_for_company` | reads a restricted file's field reviews |
| PUT /api/v1/documents/{document_id}/reviews | api/documents.py:1046 | document id | team join in `get_document_for_company` | records a review on a restricted file |
| DELETE /api/v1/documents/{document_id}/reviews/{field_key} | api/documents.py:1101 | document id | team join in `get_document_for_company` | reverts a review on a restricted file |
| GET /api/v1/documents/{document_id}/boxes | api/documents.py:1124 | document id; reads stored bytes | team join in `get_document_for_company` | reads a restricted file's extracted values |
| GET /api/v1/documents/{document_id}/page/{page_number} | api/documents.py:1177 | document id; renders page image | team join in `get_document_for_company` | shows a restricted file's document page |
| GET /api/v1/documents/{document_id}/download | api/documents.py:1241 | document id; streams the file | team join in `get_document_for_company` | downloads a restricted file's document |
| DELETE /api/v1/documents/{document_id} | api/documents.py:1263 | document id | team join in `get_document_for_company` | deletes a restricted file's document |

### C4. Stated financials by item id — `get_stated_*_for_company` (`services/stated_financials.py:189, 201, 213, 226`, join to `LoanFile` and filter company)

| Route | file:line | How it reaches the file | Enforcement point | Risk if missed |
|---|---|---|---|---|
| PATCH /api/v1/stated-liabilities/{item_id} | api/stated_financials.py:161 | item id → `StatedLiability.loan_file_id` → company | team join in `get_stated_liability_for_company` | edits a restricted file's liability |
| DELETE /api/v1/stated-liabilities/{item_id} | api/stated_financials.py:184 | item id | team join in `get_stated_liability_for_company` | deletes a restricted file's liability |
| PATCH /api/v1/stated-assets/{item_id} | api/stated_financials.py:236 | item id → `StatedAsset.loan_file_id` | team join in `get_stated_asset_for_company` | edits a restricted file's asset |
| DELETE /api/v1/stated-assets/{item_id} | api/stated_financials.py:258 | item id | team join in `get_stated_asset_for_company` | deletes a restricted file's asset |
| PATCH /api/v1/stated-income-items/{item_id} | api/stated_financials.py:317 | item id → borrower → file | team join in `get_stated_income_for_company` | edits a restricted file's income |
| DELETE /api/v1/stated-income-items/{item_id} | api/stated_financials.py:340 | item id → borrower → file | team join in `get_stated_income_for_company` | deletes a restricted file's income |
| PATCH /api/v1/stated-employers/{item_id} | api/stated_financials.py:400 | item id → borrower → file | team join in `get_stated_employer_for_company` | edits a restricted file's employer |
| DELETE /api/v1/stated-employers/{item_id} | api/stated_financials.py:423 | item id → borrower → file | team join in `get_stated_employer_for_company` | deletes a restricted file's employer |

The PATCH responses return the edited row, so each of these is a read as well as a write.

### C5. Company-wide lists and counts

| Route | file:line | How it reaches the file | Enforcement point | Risk if missed |
|---|---|---|---|---|
| GET /api/v1/inbound/queue | api/inbound.py:169 | `list_triage_queue` (`services/inbound_triage.py:651`) filters only `InboundMessage.company_id` and excludes rejected-with-no-file; ROUTED messages (on a file) are included, with `loan_file_id`, `from_address`, `subject` | team filter in `list_triage_queue` for rows with a `loan_file_id`; rows with no file stay visible (ADR-421) | lists mail on another team's files |
| POST /api/v1/inbound/messages/{message_id}/move | api/inbound.py:191 | message id (must be UNROUTED), then target file via `get_loan_file` inside `move_unrouted_message` (`services/inbound_triage.py:577`, call at 608) | team check on the target file in `move_unrouted_message` | files mail onto a restricted file by display id |
| GET /api/v1/reminders | api/reminders.py:69 | `build_suggestions(company_id)` (`services/reminders.py:342`) → `_open_files` (104) selects every open `LoanFile` of the company | team filter in `_open_files` | lists nudges for another team's files |
| GET /api/v1/saved-views?with_counts=true | api/saved_views.py:73 | `count_loan_files` (`services/loan_files.py:154`) per view, through `_scoped` (114) | team filter in `_scoped` / `count_loan_files`, shared with `list_loan_files` | counts include restricted files |
| POST /api/v1/admin/lenders/{lender_id}/overlay/blast-radius | api/overlay_admin.py:66 | `estimate_blast_radius` (`services/overlay_blast_radius.py:142`) returns `AffectedFile` rows (`loan_file_id`, `display_id`) for the lender's open files | none today: router requires `overlays.manage`, which only ADMIN holds (`core/permissions.py`), and ADMIN holds every permission including `loan.view_all`; filter if that cell ever changes | lists restricted files' display ids (only if non-admins gain `overlays.manage`) |

### C6. Token and dev-only doors

| Route | file:line | How it reaches the file | Enforcement point | Risk if missed |
|---|---|---|---|---|
| GET /api/v1/upload/{token} | api/upload_links.py:198 | unauthenticated; `resolve_link` (`services/upload_links.py:177`) by token hash → `link_for_loan_file` | none: the token is the credential for an outside party, no staff user involved | none: not a staff read |
| POST /api/v1/upload/{token} | api/upload_links.py:228 | unauthenticated; token → link → `redeem_link` | none: as above | none: not a staff read |
| POST /api/v1/dev/documents/{document_id}/extract-text-layer | api/dev.py:54 | document id via `get_document_for_company`; mounted only when not production (`main.py:204-208`) | covered by the C3 fix in `get_document_for_company` | dev/staging only: reads a restricted file's document text |

---

## Group B — `get_loan_file` / `list_loan_files` called directly

These resolve the file from the path (or list files) but not through `get_scoped_loan_file`. Enforcement
options: move each onto `ScopedLoanFile`, or make the team check part of a lookup they all share. Note
that `get_loan_file` (`services/loan_files.py:210`) takes only `company_id`, not the actor, and is also
called from `services/inbound_triage.py:608`, so putting the check inside it means changing its
signature at every caller.

### B1. Conditions router's own dependency — `ScopedLoanFileById` (`api/conditions.py:411`, calls `get_loan_file` at 435)

One enforcement point covers all 29: the team check in `get_scoped_loan_file_by_id` (or make it delegate
to `get_scoped_loan_file`). Child ids in these paths (draft_id, condition_id) are checked against the
path's file (`_scoped_draft` at 2299; restore filters `Condition.loan_file_id == loan_file.id` at 2744).

| Route | file:line | How it reaches the file | Enforcement point | Risk if missed |
|---|---|---|---|---|
| POST /api/v1/loan-files/{loan_file_id}/condition-rounds/uploads | api/conditions.py:466 | `ScopedLoanFileById` | `get_scoped_loan_file_by_id` | uploads a sheet to a restricted file |
| GET /api/v1/loan-files/{loan_file_id}/condition-rounds | api/conditions.py:556 | `ScopedLoanFileById` | `get_scoped_loan_file_by_id` | lists a restricted file's rounds |
| PUT /api/v1/loan-files/{loan_file_id}/lender-processing | api/conditions.py:599 | `ScopedLoanFileById` | `get_scoped_loan_file_by_id` | edits a restricted file |
| GET /api/v1/loan-files/{loan_file_id}/conditions | api/conditions.py:761 | `ScopedLoanFileById` | `get_scoped_loan_file_by_id` | lists a restricted file's conditions |
| GET /api/v1/loan-files/{loan_file_id}/conditions/summary | api/conditions.py:881 | `ScopedLoanFileById` | `get_scoped_loan_file_by_id` | reads a restricted file's condition summary |
| POST /api/v1/loan-files/{loan_file_id}/condition-rounds/paste | api/conditions.py:922 | `ScopedLoanFileById` | `get_scoped_loan_file_by_id` | adds conditions to a restricted file |
| GET /api/v1/loan-files/{loan_file_id}/conditions/lender | api/conditions.py:1523 | `ScopedLoanFileById` | `get_scoped_loan_file_by_id` | reads a restricted file's lender |
| PUT /api/v1/loan-files/{loan_file_id}/conditions/lender | api/conditions.py:1529 | `ScopedLoanFileById` | `get_scoped_loan_file_by_id` | sets a restricted file's lender |
| POST /api/v1/loan-files/{loan_file_id}/conditions/lender/decline | api/conditions.py:1565 | `ScopedLoanFileById` | `get_scoped_loan_file_by_id` | edits a restricted file |
| POST /api/v1/loan-files/{loan_file_id}/conditions | api/conditions.py:1585 | `ScopedLoanFileById` | `get_scoped_loan_file_by_id` | adds a condition to a restricted file |
| POST /api/v1/loan-files/{loan_file_id}/conditions/bulk | api/conditions.py:2116 | `ScopedLoanFileById` | `get_scoped_loan_file_by_id` | bulk-edits a restricted file's conditions |
| GET /api/v1/loan-files/{loan_file_id}/condition-drafts | api/conditions.py:2307 | `ScopedLoanFileById` | `get_scoped_loan_file_by_id` | lists a restricted file's drafts |
| GET /api/v1/loan-files/{loan_file_id}/condition-drafts/{draft_id} | api/conditions.py:2316 | `ScopedLoanFileById` + `_scoped_draft` | `get_scoped_loan_file_by_id` | reads a restricted file's draft |
| POST /api/v1/loan-files/{loan_file_id}/condition-drafts/{draft_id}/mark-sent | api/conditions.py:2326 | `ScopedLoanFileById` + `_scoped_draft` | `get_scoped_loan_file_by_id` | edits a restricted file's draft |
| DELETE /api/v1/loan-files/{loan_file_id}/condition-drafts/{draft_id} | api/conditions.py:2349 | `ScopedLoanFileById` + `_scoped_draft` | `get_scoped_loan_file_by_id` | deletes a restricted file's draft |
| PUT /api/v1/loan-files/{loan_file_id}/condition-drafts/{draft_id}/address | api/conditions.py:2364 | `ScopedLoanFileById` + `_scoped_draft` | `get_scoped_loan_file_by_id` | edits a restricted file's draft |
| PUT /api/v1/loan-files/{loan_file_id}/condition-drafts/{draft_id}/due-date | api/conditions.py:2389 | `ScopedLoanFileById` + `_scoped_draft` | `get_scoped_loan_file_by_id` | edits a restricted file's draft |
| POST /api/v1/loan-files/{loan_file_id}/condition-drafts/{draft_id}/polish | api/conditions.py:2416 | `ScopedLoanFileById` + `_scoped_draft` | `get_scoped_loan_file_by_id` | polishes a restricted file's draft |
| PUT /api/v1/loan-files/{loan_file_id}/condition-drafts/{draft_id}/body | api/conditions.py:2436 | `ScopedLoanFileById` + `_scoped_draft` | `get_scoped_loan_file_by_id` | edits a restricted file's draft |
| GET /api/v1/loan-files/{loan_file_id}/figures-check | api/conditions.py:2538 | `ScopedLoanFileById` | `get_scoped_loan_file_by_id` | reads a restricted file's figures |
| POST /api/v1/loan-files/{loan_file_id}/figures-check/apply | api/conditions.py:2547 | `ScopedLoanFileById` | `get_scoped_loan_file_by_id` | edits a restricted file's figures |
| GET /api/v1/loan-files/{loan_file_id}/condition-package | api/conditions.py:2594 | `ScopedLoanFileById` | `get_scoped_loan_file_by_id` | reads a restricted file's package |
| POST /api/v1/loan-files/{loan_file_id}/condition-package/build | api/conditions.py:2602 | `ScopedLoanFileById` | `get_scoped_loan_file_by_id` | builds a restricted file's package |
| PATCH /api/v1/loan-files/{loan_file_id}/condition-package/rows/{condition_id} | api/conditions.py:2619 | `ScopedLoanFileById`; row via `_open_package(loan_file)` | `get_scoped_loan_file_by_id` | edits a restricted file's package |
| POST /api/v1/loan-files/{loan_file_id}/condition-package/du-rerun-done | api/conditions.py:2644 | `ScopedLoanFileById` | `get_scoped_loan_file_by_id` | edits a restricted file's package |
| POST /api/v1/loan-files/{loan_file_id}/condition-package/submit | api/conditions.py:2659 | `ScopedLoanFileById` | `get_scoped_loan_file_by_id` | submits a restricted file's package |
| GET /api/v1/loan-files/{loan_file_id}/condition-package/download | api/conditions.py:2679 | `ScopedLoanFileById` | `get_scoped_loan_file_by_id` | downloads a restricted file's package |
| POST /api/v1/loan-files/{loan_file_id}/conditions/{condition_id}/restore | api/conditions.py:2731 | `ScopedLoanFileById` | `get_scoped_loan_file_by_id` | restores a restricted file's condition |
| GET /api/v1/loan-files/{loan_file_id}/withdrawn-conditions | api/conditions.py:2756 | `ScopedLoanFileById` | `get_scoped_loan_file_by_id` | lists a restricted file's withdrawn conditions |

### B2. Loan file routes — `api/loan_files.py`

| Route | file:line | How it reaches the file | Enforcement point | Risk if missed |
|---|---|---|---|---|
| POST /api/v1/loan-files | api/loan_files.py:89 | creates, then re-reads with `get_loan_file` | creator must be on the team (Part 1 "On create") before the re-read, or the create answers 404 | creator gets 404 on their own new file (correctness, not leak) |
| POST /api/v1/loan-files/import-mismo | api/loan_files.py:125 | creates from MISMO, then re-reads with `get_loan_file` | as above | as above |
| GET /api/v1/loan-files | api/loan_files.py:213 | `list_loan_files` (`services/loan_files.py:171`) through `_scoped` (114); also `attention_for_files` on the page | team filter in `_scoped` (shared with `count_loan_files`) | dashboard lists another team's files |
| GET /api/v1/loan-files/{identifier} | api/loan_files.py:249 | `get_loan_file` | team check (move to `ScopedLoanFile` or shared lookup) | opens a restricted file |
| GET /api/v1/loan-files/{identifier}/stated-financials | api/loan_files.py:259 | `get_loan_file` | as above | reads a restricted file's stated financials |
| PATCH /api/v1/loan-files/{identifier} | api/loan_files.py:277 | `get_loan_file` | as above | edits a restricted file |
| DELETE /api/v1/loan-files/{identifier} | api/loan_files.py:329 | `get_loan_file` | as above | deletes a restricted file |
| GET /api/v1/loan-files/{identifier}/reconciliation | api/loan_files.py:343 | `get_loan_file` | as above | reads a restricted file's reconciliation |

### B3. Calculators, DTI, LTV — `api/calculators.py`, `api/dti.py`, `api/ltv.py`

| Route | file:line | How it reaches the file | Enforcement point | Risk if missed |
|---|---|---|---|---|
| GET /api/v1/loan-files/{identifier}/calculators/{calculator} | api/calculators.py:40 | `get_loan_file` | team check (move to `ScopedLoanFile` or shared lookup) | reads a restricted file's calculator |
| PUT /api/v1/loan-files/{identifier}/calculators/{calculator}/overrides/{field_key} | api/calculators.py:57 | `get_loan_file` | as above | edits a restricted file's calculator |
| DELETE /api/v1/loan-files/{identifier}/calculators/{calculator}/overrides/{field_key} | api/calculators.py:92 | `get_loan_file` | as above | edits a restricted file's calculator |
| GET /api/v1/loan-files/{identifier}/dti | api/dti.py:41 | `get_loan_file` | as above | reads a restricted file's DTI |
| POST /api/v1/loan-files/{identifier}/dti/lines | api/dti.py:54 | `get_loan_file` | as above | edits a restricted file's DTI |
| DELETE /api/v1/loan-files/{identifier}/dti/lines/{line_id} | api/dti.py:81 | `get_loan_file` | as above | edits a restricted file's DTI |
| GET /api/v1/loan-files/{identifier}/dti/ungate | api/dti.py:110 | `get_loan_file` | as above | reads a restricted file's DTI |
| POST /api/v1/loan-files/{identifier}/dti/ungate | api/dti.py:123 | `get_loan_file` | as above | edits a restricted file's DTI |
| PUT /api/v1/loan-files/{identifier}/dti/overrides/{field_key} | api/dti.py:150 | `get_loan_file` | as above | edits a restricted file's DTI |
| DELETE /api/v1/loan-files/{identifier}/dti/overrides/{field_key} | api/dti.py:179 | `get_loan_file` | as above | edits a restricted file's DTI |
| GET /api/v1/loan-files/{identifier}/ltv | api/ltv.py:28 | `get_loan_file` | as above | reads a restricted file's LTV |
| PUT /api/v1/loan-files/{identifier}/ltv/overrides/{field_key} | api/ltv.py:39 | `get_loan_file` | as above | edits a restricted file's LTV |
| DELETE /api/v1/loan-files/{identifier}/ltv/overrides/{field_key} | api/ltv.py:68 | `get_loan_file` | as above | edits a restricted file's LTV |

### B4. Verification and findings — `api/verification.py`

Finding ids are resolved through `_get_finding(loan_file=…)` (`api/verification.py:223`), so the file in
the path is the gate.

| Route | file:line | How it reaches the file | Enforcement point | Risk if missed |
|---|---|---|---|---|
| POST /api/v1/loan-files/{identifier}/verification/run | api/verification.py:363 | `get_loan_file` | team check (move to `ScopedLoanFile` or shared lookup) | runs verification on a restricted file |
| GET /api/v1/loan-files/{identifier}/verification | api/verification.py:655 | `get_loan_file` | as above | reads a restricted file's findings |
| PUT /api/v1/loan-files/{identifier}/verification/aggression | api/verification.py:667 | `get_loan_file` | as above | edits a restricted file |
| GET /api/v1/loan-files/{identifier}/findings/{finding_id}/apply-preview | api/verification.py:693 | `get_loan_file` + `_get_finding` | as above | reads a restricted file's finding |
| GET /api/v1/loan-files/{identifier}/snapshot-findings | api/verification.py:730 | `get_loan_file` | as above | lists a restricted file's findings |
| POST /api/v1/loan-files/{identifier}/snapshot-findings/{finding_id}/disposition | api/verification.py:763 | `get_loan_file` | as above | edits a restricted file's finding |
| POST /api/v1/loan-files/{identifier}/findings/{finding_id}/apply | api/verification.py:816 | `get_loan_file` + `_get_finding` | as above | edits a restricted file |
| POST /api/v1/loan-files/{identifier}/findings/request-docs | api/verification.py:872 | `get_loan_file` | as above | drafts a request on a restricted file |
| POST /api/v1/loan-files/{identifier}/findings/{finding_id}/ratify | api/verification.py:941 | `get_loan_file` + `_get_finding` | as above | edits a restricted file's finding |
| POST /api/v1/loan-files/{identifier}/findings/{finding_id}/undo | api/verification.py:971 | `get_loan_file` + `_get_finding` | as above | edits a restricted file's finding |
| POST /api/v1/loan-files/{identifier}/findings/{finding_id}/override | api/verification.py:996 | `get_loan_file` + `_get_finding` | as above | edits a restricted file's finding |
| POST /api/v1/loan-files/{identifier}/findings/{finding_id}/note | api/verification.py:1025 | `get_loan_file` + `_get_finding` | as above | edits a restricted file's finding |
| POST /api/v1/loan-files/{identifier}/findings/{finding_id}/accept-risk | api/verification.py:1055 | `get_loan_file` + `_get_finding` | as above | edits a restricted file's finding |
| POST /api/v1/loan-files/{identifier}/findings/{finding_id}/request-docs | api/verification.py:1136 | `get_loan_file` + `_get_finding` | as above | drafts a request on a restricted file |
| GET /api/v1/loan-files/{identifier}/verification/runs | api/verification.py:1211 | `get_loan_file` | as above | lists a restricted file's runs |

### B5. Stated financials, add — `api/stated_financials.py`

Borrower ids are resolved with `get_borrower(loan_file_id=loan_file.id, …)`, so the file is the gate.

| Route | file:line | How it reaches the file | Enforcement point | Risk if missed |
|---|---|---|---|---|
| POST /api/v1/loan-files/{file_identifier}/stated-liabilities | api/stated_financials.py:133 | `get_loan_file` | team check (move to `ScopedLoanFile`; the path already uses `file_identifier`) | adds to a restricted file |
| POST /api/v1/loan-files/{file_identifier}/stated-assets | api/stated_financials.py:209 | `get_loan_file` | as above | adds to a restricted file |
| POST /api/v1/loan-files/{file_identifier}/borrowers/{borrower_id}/stated-income | api/stated_financials.py:283 | `get_loan_file` + `get_borrower` | as above | adds to a restricted file |
| POST /api/v1/loan-files/{file_identifier}/borrowers/{borrower_id}/stated-employers | api/stated_financials.py:366 | `get_loan_file` + `get_borrower` | as above | adds to a restricted file |

---

## Group A — through `ScopedLoanFile` / `get_scoped_loan_file` (`api/dependencies.py:200`)

One enforcement fix in `get_scoped_loan_file` covers all 64. It currently takes `current_user`, not the
`Actor`, so the fix needs the actor's permissions (`loan.view_all`) and `sees_all_loans`, plus the company
setting `restrict_loans_to_team`.

The fix holds only if every child id in these paths is matched to the path's file and not merely to
the company. Spot-checked and found matched: borrowers (`get_borrower(loan_file_id=…)`), needs
(`_scoped_need`, `api/needs.py:77`), inbound attachments (`_scoped_attachment`, `api/inbound.py:243`,
checks `message.loan_file_id`), upload-link revoke (`api/upload_links.py:175` checks
`link.loan_file_id`), party-request addresses (`remove_participant(loan_file=…)`), outbound drafts
(`delete_draft(loan_file=…)`), messages (`read_message` docstring: service checks `loan_file_id` on the
row). Not every service was opened; a per-route test in Part 2 ("a non-member processor gets 404") is what
proves the rest.

| Router file | Routes | Line range | Paths |
|---|---|---|---|
| api/activity.py | 1 | 24 | /api/v1/loan-files/{file_identifier}/activity |
| api/borrowers.py | 5 | 34–73 | /api/v1/loan-files/{file_identifier}/borrowers[/{borrower_id}] |
| api/communications.py | 19 | 80–1008 | /api/v1/loan-files/{file_identifier}/outbound/…, /messages/…, /follow-ups |
| api/document_findings.py | 1 | 19 | /api/v1/loan-files/{file_identifier}/findings |
| api/documents.py | 3 | 343–448 | /api/v1/loan-files/{file_identifier}/documents[/reprocess] |
| api/evidence.py | 4 | 97–141 | /api/v1/loan-files/{file_identifier}/evidence, /legal-hold |
| api/inbound.py | 5 | 176–458 | /api/v1/loan-files/{file_identifier}/inbound/messages, /inbound/attachments/{attachment_id}/… |
| api/lenders.py | 1 | 241 | PUT /api/v1/loan-files/{file_identifier}/underwriter |
| api/needs.py | 10 | 85–301 | /api/v1/loan-files/{file_identifier}/needs[/{needs_item_id}/…] |
| api/party_requests.py | 4 | 86–132 | /api/v1/loan-files/{file_identifier}/party-requests/… |
| api/property.py | 4 | 34–92 | /api/v1/loan-files/{file_identifier}/property |
| api/reminders.py | 3 | 76–116 | /api/v1/loan-files/{file_identifier}/reminders[/snooze, /unsnooze] |
| api/timeline.py | 1 | 128 | /api/v1/loan-files/{file_identifier}/timeline |
| api/upload_links.py | 3 | 122–166 | /api/v1/loan-files/{file_identifier}/upload-links[/{link_id}] |
| **Total** | **64** | | |

---

## Group D — Celery tasks and beat jobs

No task has a user; none applies a team check, and none should need one for its own reads. The Part 2
question for each is whether it delivers file content to a person, and to whom. Each user-triggered job
is enqueued by a route listed above, so the gate is at that route.

| Task | file:line | How it reaches the file | Enforcement point | Risk if missed |
|---|---|---|---|---|
| documents.process_document | tasks/document_processing.py:1015 | document id → its file; enqueued from api/documents.py:254, 279, api/inbound.py:306, api/upload_links.py:223 | none in the job; gate is the enqueuing route | none: system job, no user |
| documents.reprocess_document | tasks/document_processing.py:1057 | document id; enqueued from api/documents.py:293 | none in the job | none: system job, no user |
| needs.update_for_document | tasks/needs.py:115 | loan_file_id + document_id; enqueued from tasks/document_processing.py:118 | none in the job | none: system job, no user |
| needs.propose_ai_needs | tasks/needs.py:132 | loan_file_id; enqueued from api/loan_files.py:63 (MISMO import) | none in the job | none: system job, no user |
| verification.run_rule_engine | tasks/verification_rules.py:73 | loan_file_id + run_id; enqueued from api/verification.py:346 | none in the job | none: system job, no user |
| verification.run_cross_source | tasks/cross_source.py:28 | `db.get(LoanFile, loan_file_id)`; AMBIGUOUS: grep found no `.delay`/`.apply_async` of it in `app/` (only a comment at tasks/celery_app.py:88) | none in the job | none: system job, no user (and apparently not enqueued) |
| conditions.parse_condition_round | tasks/conditions.py:496 | round id → file; enqueued from api/conditions.py:523, api/inbound.py:449, and `_enqueue_parse_or_fail` (api/conditions.py:324) | none in the job | none: system job, no user |
| conditions.split_condition_round | tasks/conditions.py:526 | round id; enqueued from tasks/conditions.py:184 | none in the job | none: system job, no user |
| conditions.read_condition_round | tasks/conditions.py:616 | round id; enqueued from api/conditions.py:243 | none in the job | none: system job, no user |
| email_draft.compose_prose | tasks/email_draft.py:49 | loan_file_id; enqueued from api/verification.py:1133 on behalf of the requesting user | none in the job; writes a draft on the file that the user then reads through group B/A routes | none: system job, output read through gated routes |
| communications.send | tasks/outbound.py:237 | communication id → file; enqueued from api/communications.py:326 (a person's approved Send), tasks/follow_ups.py:189, tasks/outbound.py:264 | none in the job | none: sends to external recipients the user approved |
| communications.requeue_stale | tasks/outbound.py:279 | beat, every 300 s (tasks/celery_app.py:113); system-wide stale sends | none | none: system job, no user |
| communications.read_delivery_events | tasks/outbound.py:363 | beat, every 60 s (tasks/celery_app.py:120); `apply_delivery_event` updates communications by provider event | none | none: system job, no user |
| communications.send_follow_ups | tasks/follow_ups.py:199 | beat, every 900 s (tasks/celery_app.py:140); `candidates_stmt` (57) selects due follow-ups across every company | none | none: system job, mail goes to external recipients |
| inbound.poll_queue | tasks/inbound.py:110 | beat, every 60 s (tasks/celery_app.py:126); `process_raw_message` stores and routes mail onto files, then calls `_copy_to_processor` (73) | none for routing; see next row for the copy | none for routing: system job |
| inbound.copy_to_processor | tasks/inbound.py:102 (body `_copy_to_processor` at 77) | message id → file; `copy_recipient` (`services/processor_copy.py:57`) picks the approver of the most recent Send on the file — any active user of the company, not a team member | decide whether `copy_recipient` should require current team membership when the setting is on | emails a restricted file's inbound mail to a user no longer on its team |

---

## Not file reads (checked and excluded)

Routes (52):

- `api/auth.py` (4): login, refresh, logout, me.
- `api/users.py` (6) and `api/preferences.py` (2): people and the caller's own preferences.
- `api/company.py` (2): company settings.
- `api/invites.py` (6): staff invites and accept.
- `api/audit_log.py` (1): admin action log, `audit.view` only.
- `api/lenders.py` (10 of 11): lenders, contacts and condition settings; the one file route (`PUT /loan-files/{file_identifier}/underwriter`) is in group A.
- `api/overlay_admin.py` (3 of 4): lender overlay list/read/write; the blast-radius route is in C5.
- `api/mailbox_connections.py` (5): company mailbox connections.
- `api/validation_aid.py` (2): rule inventory and verdicts; `services/validation_aid.py` has no `LoanFile`/`loan_file` reference.
- `api/capabilities.py` (1): deployment flags and `company_receives_mail`.
- `api/dev_bench.py` (4): extraction bench over local paths; no `LoanFile`/`Document` reference; development only.
- `api/dev.py` `POST /api/v1/dev/inbound/inject` (1): injects a raw message through the routing pipeline; returns only the message id, ingest key and a flag; dev/staging only.
- `api/documents.py` `GET /api/v1/documents/types/catalog` (1): static type list.
- `api/inbound.py` `POST /api/v1/inbound/messages/{message_id}/dismiss` (1): refuses any message not `UNROUTED`, so it only touches mail with no file (ADR-421).
- `api/saved_views.py` POST, PATCH, DELETE (3): saved view rows only; the counts on `GET` are in C5.
- Health endpoints (`/health`, `/health/live`, `/health/ready`) are defined in `app/main.py`, not `app/api/`.

Tasks (5): `health.ping`, `health.db_ping`, `health.heartbeat` (tasks/health.py), `invites.send_invite_email`
(tasks/invites.py:97), `mail_domains.check_all` (tasks/mail_domains.py:57).

## Method

Read `backend/app/api/dependencies.py` in full, `app/main.py` router mounts (lines 60–217), and the
Part 2 section of `docs/tickets/LP-MB-Admin-05.md`. Enumerated every route by parsing each
`app/api/*.py` with Python's `ast` (router variables and prefixes, decorator method/path/line, parameter
annotations containing `Scoped`, and called function names): 253 routes. Grepped `app/` for
`ScopedLoanFile`, `get_scoped_loan_file`, `get_loan_file(`, `list_loan_files(`, `count_loan_files(`,
`Scoped[A-Za-z]* = Annotated`, `_scoped`, `company_id ==`, `.delay(` and `.apply_async(`. Read
`get_scoped_round`, `get_scoped_condition`, `get_scoped_loan_file_by_id` (api/conditions.py:347–443),
`services/loan_files.py:114–232`, `services/documents.py:206`, `services/stated_financials.py:189–237`,
`services/inbound_triage.py:577–680`, `services/reminders.py:104–115, 342–360`, `api/saved_views.py:55–112`,
`api/overlay_admin.py`, `services/overlay_blast_radius.py` (classes), `api/validation_aid.py`,
`api/audit_log.py`, `api/capabilities.py`, `core/permissions.py`, `services/upload_links.py:177`,
`services/processor_copy.py:57–83`, and the child-id checks named under group A. Listed tasks with
grep for `@celery_app.task` and read `tasks/celery_app.py` (`_TASK_MODULES` and `beat_schedule`).
Nothing was run against a database and no tests were run.

## Addendum: routes added by LP-MB-Admin-05 Part 1

The survey above was taken while Part 1 was being written and counts 253 routes. Part 1 adds six,
measured afterwards (255 decorated routes before `loan_teams.py`, which adds 4):

| Group | Route | file | How it reaches the file | Enforcement Part 2 would need | Risk if missed |
|---|---|---|---|---|---|
| A | `GET /api/v1/loan-files/{file_identifier}/team` | `api/loan_teams.py` | `ScopedLoanFile` | the ScopedLoanFile dependency | shows a restricted file's team |
| A | `PUT /api/v1/loan-files/{file_identifier}/team/loan-officer` | `api/loan_teams.py` | `ScopedLoanFile` | the ScopedLoanFile dependency (writes are also limited to Admin / the file's LO) | changes a restricted file's team |
| A | `POST /api/v1/loan-files/{file_identifier}/team/members` | `api/loan_teams.py` | `ScopedLoanFile` | as above | as above |
| A | `DELETE /api/v1/loan-files/{file_identifier}/team/members/{member_id}` | `api/loan_teams.py` | `ScopedLoanFile` | as above | as above |
| C | `GET /api/v1/users/assignable` | `api/users.py` | company-wide count of each person's live files (`loan_teams.live_place_counts`) | none for the names; the counts include restricted files | reveals how many files a colleague works, not which |
| C | `POST /api/v1/users/{user_id}/reassign-loans` | `api/users.py` | every live team row of one user, company-wide | none: `users.manage` (Admin), who sees every file | none while only Admins hold `users.manage` |

The list and detail routes (`GET /loan-files`, `GET /loan-files/{identifier}`) now also return each
file's `team`; they were already in the survey (group B), and the new `assignee` filter narrows them
rather than widening them.

**Totals with Part 1:** A 68, B 69, C 70, D 16; 223.
