# Are loan files scoped to a company or to a user?

**Date:** 2026-08-13 · **Scope:** read-only. Nothing was modified.

---

## Answer

**Correct behaviour. Your hypothesis is right, and the code establishes it rather
than merely being consistent with it.**

Loan files are scoped to a **company**. There is no per-user ownership anywhere in
the system — not a column, not a table, not a filter. Two `ADMIN` users in company
`mb` seeing the same loan file is the designed visibility model, not a leak.

The between-company boundary — the one that actually matters — is enforced, and it
is enforced structurally rather than route by route: **81 of 81 routes** are gated,
and the gate derives from the authenticated user's record rather than from anything
the caller can send.

One thing worth fixing is noted at the end. It is **not** the cause of what you
observed and it is **not** currently reachable.

---

## DATA — the schema

### 1. `loan_files` carries `company_id` and nothing else that could scope ownership

`backend/app/models/loan_file.py:141-152`:

```python
# --- Ownership ---------------------------------------------------------
company_id: Mapped[UUID] = mapped_column(
    ForeignKey("companies.id", ondelete="RESTRICT"),
    index=True,
    nullable=False,
)
# Nullable: the lender may be unassigned when the file is first created.
lender_id: Mapped[UUID | None] = mapped_column(
    ForeignKey("lenders.id", ondelete="RESTRICT"),
    index=True,
    nullable=True,
)
```

That block is the whole of ownership. Across all 30 mapped columns there is **no
`created_by_user_id`, no `owner_id`, no `assigned_to`, no `user_id`**. A grep for
`assigned|assignee|shared_with|owner_id|created_by` across `app/models/` returns one
hit in `loan_file.py` — the word "unassigned" in the comment above, about the
*lender*.

The only FKs on `loan_files` are `company_id` and `lender_id`.

### 2. Children carry no tenant column — scoping is transitive, by policy

`documents`, `extractions`, and the MISMO import record have **no `company_id`**.
This is a documented architectural decision (ADR-052), stated in each model's
docstring. `app/models/document.py:25`:

> ``document`` (FK ``ondelete=CASCADE``) and has no ``company_id`` of its own — it is
> company-scoped transitively through …

`app/models/mismo_import.py:16` says the same, and `MismoImport`'s only FK is
`loan_file_id` (`:56`).

Exactly four models carry `company_id`: `loan_files`, `users`, `lenders`,
`validation_verdicts`. Everything else reaches the tenant through its loan file.

### 4. There is no per-user visibility concept at all

No assignment table, no `assigned_to`, no sharing model. Company membership is the
**only** boundary.

Eight models do carry a `users.id` FK, and every one is **attribution, not
visibility**:

| model | column | meaning |
|---|---|---|
| `activity_log` | `actor_user_id` | "The user who performed the action; null = system-generated" |
| `document` | `uploaded_by_user_id` | who uploaded; null for borrower-inbox and MISMO import |
| `calculator_override`, `dti_override`, `ltv_override`, `finding`, `communication`, `validation_verdict` | actor columns | who did it |

None appears in any read filter. In the API layer, `current_user.id` is passed
exclusively as `actor_user_id=` — for example `app/api/loan_files.py:100`,
`:167`, `:280`, `:299`. Never as a `where`.

---

## DATA — the query path

### 3. Every read filters on `current_user.company_id`

The scope comes from a dependency that reads the authenticated user's record
(`app/api/dependencies.py:122-130`):

```python
def get_current_company_id(current_user: CurrentUser) -> UUID:
    """The request's tenant scope: the authenticated user's ``company_id``.

    … Because it derives from the validated token and the live user record, a
    caller cannot present another company's id …
    """
    return current_user.company_id
```

All loan-file reads funnel through one scoped base query
(`app/services/loan_files.py:114-123`):

```python
def _scoped(company_id: UUID) -> Select[tuple[LoanFile]]:
    """A base ``select(LoanFile)`` already scoped to the company and active rows.

    Centralizes the two filters every read must apply, so no call site can
    forget tenant scoping or accidentally surface soft-deleted files.
    """
    stmt = select(LoanFile)
    stmt = scope_to_company(stmt, LoanFile, company_id)
    stmt = only_active(stmt, LoanFile)
    return stmt
```

| route | filter applied |
|---|---|
| `GET /loan-files` (`api/loan_files.py:219`) | `list_loan_files(company_id=current_user.company_id, …)` → `_scoped()` |
| `GET /loan-files/{identifier}` (`:238`) | `get_loan_file(company_id=current_user.company_id, …)` → `_scoped()` |
| every nested route | `ScopedLoanFile` dependency |

**Neither filters on `current_user.id`. Neither has an unfiltered path.**

The search filter composes rather than replaces — the borrower-name subquery joins
by `loan_file_id` while the outer query stays company-scoped
(`services/loan_files.py:146-158`), so a matching borrower name in another company
cannot pull that file in.

### The nested-resource gate

`app/api/dependencies.py:136-152`:

```python
async def get_scoped_loan_file(
    file_identifier: str, db: DbSession, current_user: CurrentUser
) -> LoanFile:
    """… This is the **tenant gate** for nested resources … If the file isn't the
    caller's (or doesn't exist) it raises ``404`` and the child is never reached."""
    loan_file = await get_loan_file(
        db, company_id=current_user.company_id, identifier=file_identifier
    )
    if loan_file is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Loan file not found")
    return loan_file
```

`get_loan_file` returns `None` for another company's file, so a cross-tenant id is
**indistinguishable from a missing one** — no existence oracle.

### 5. MISMO import stamps the importing user's *company*

`app/api/loan_files.py:161-168`:

```python
loan_file = await create_loan_file_from_mismo(
    db,
    parsed=parsed,
    company_id=current_user.company_id,
    raw_content=raw,
    source_format=parsed.source_format,
    actor_user_id=current_user.id,
)
```

`company_id` is the tenant; `actor_user_id` is attribution only. The route docstring
states it explicitly: *"``company_id`` is the authenticated user's (never the body)."*

**This is precisely why your second user sees the file.** The import stamped
company `mb`, not the importing user, and the reader filters on company.

---

## DATA — the cross-company boundary

### 6. Audit of all 81 routes

Every route handler in `app/api/` was classified by the gate it applies:

| gate | routes |
|---|---|
| `ScopedLoanFile` (nested) | 20 |
| `current_user.company_id` / `CurrentCompanyId` | 55 |
| none — **and correctly so** | 6 |

The six ungated ones are `auth.py`'s `login`, `refresh`, `logout`,
`read_current_user`, and `preferences.py`'s two handlers. The auth endpoints are the
authentication boundary itself; the preferences handlers read and write
`current_user` **directly** (`api/preferences.py:22`,`:35`) — that object *is* the
caller, so there is nothing to scope.

**No business route lacks a tenant gate.**

Flat routes that take a child id resolve it through a join back to the loan file.
`app/services/documents.py:195-214`:

```python
async def get_document_for_company(
    db: AsyncSession, *, document_id: UUID, company_id: UUID
) -> Document | None:
    """… documents have no ``company_id``, so this joins ``Document -> LoanFile``
    and filters on the file's company. Returns ``None`` if the document doesn't
    exist, is soft-deleted, lives under a soft-deleted file, or belongs to another
    company — the endpoint turns that into ``404`` …"""
    stmt = (
        select(Document)
        .join(LoanFile, Document.loan_file_id == LoanFile.id)
        .where(Document.id == document_id, LoanFile.company_id == company_id)
    )
```

`stated_financials` uses the same `*_for_company` pattern for all twelve of its
routes.

**A user in company A cannot retrieve a loan file belonging to company B** — not by
list, not by direct id, not by display id, and not through any nested or flat child
route.

### 7. Queries reaching `loan_files` / `documents` / `extractions` without a company filter

43 such queries exist. 29 carry a company or loan-file constraint in their own
function. The remaining **14** do not, and each was traced to its callers:

| location | why it is not reachable unscoped |
|---|---|
| `services/documents.py:174` `get_version_group_documents` | signature is `(*, document: Document)` — an **already-authorized object**; sole caller `api/documents.py:221` obtained it from `get_document_for_company` |
| `services/documents.py:233` `get_current_extraction` | same: `(*, document: Document)`, callers at `documents.py:273,280` |
| `services/document_versioning.py:77` `version_counts_for_group_ids` | called only from `build_document_responses`, over documents already returned by a scoped query |
| `services/extractions.py:51` `create_extraction_version` | write path, from the processing pipeline |
| `services/loan_file_ids.py:70` `generate_unique_display_id` | **correctly** unscoped — `display_id` is globally unique by design (`loan_file.py:134`, `unique=True`) |
| `tasks/document_processing.py:84`, `tasks/needs.py:59` `_load_document` | Celery tasks; the `document_id` is enqueued by the upload route *after* the document was created under a `ScopedLoanFile`. Not user-supplied |
| `verification/snapshot/documents_section.py:1601` `_links_by_document` | internal to snapshot building, which starts from a scoped loan file (`snapshot/builder.py:76` is scoped) |
| `services/document_borrower_links.py:37,116,117` | **see below** |
| `scripts/*_smoke.py` (3) | developer scripts, no HTTP surface |

**The pattern is deliberate:** these helpers take an already-resolved ORM object
rather than a raw id, so authorization happens once at the boundary and cannot be
re-litigated wrongly downstream.

### ⚠️ The A2 pattern still exists — as dead code

`app/services/document_borrower_links.py:116-117`, `get_document_borrower_links`,
filters on `document_id` alone with no join back to the loan file. That is the
pattern the earlier A2 recon flagged.

**It is not reachable.** Its only callers are in
`tests/services/test_document_borrower_links.py` (lines 119, 135, 140). No route, no
service, no task calls it. The sibling `assign_document_borrower_links` takes a
`Document` **object**, not an id, and is called from the pipeline and one dev script.

So: not the cause of your observation, not currently exploitable, and worth deleting
or scoping before someone wires a route to it. **Reported, not fixed**, per your
instruction. No other instance of this pattern exists.

---

## INFERENCE

- **Your observation is fully explained by the design**, and every step of it is now
  DATA rather than inference: reads filter on company (§3), MISMO import stamps the
  importing user's company (§5), and both users and the file carry the same
  `company_id` in the staging rows (§8). Nothing here is assumed.
- **The boundary is structural, not incidental.** One `_scoped()` helper, one
  `get_current_company_id` dependency, one `ScopedLoanFile` gate, and a
  `*_for_company` convention for flat routes. That is why 81/81 routes hold: a
  developer would have to work around the pattern rather than merely forget it.
- **The tenant scope is not forgeable.** It comes from the live user record behind a
  validated token, never from a path, query, or body parameter.

---

## The intended visibility model — for documentation

> **A loan file belongs to a company, not to a person.**
>
> Every user of a company sees, and can act on, every one of that company's loan
> files. There is no per-user ownership, no assignment, and no sharing: colleagues at
> the same broker shop share a workload by design.
>
> `role` (`ADMIN` | `PROCESSOR`) grants *capabilities*, not *visibility*. The only
> admin-gated surfaces are `overlay_admin` and `validation_aid`
> (`require_role(UserRole.ADMIN)`); a `PROCESSOR` sees exactly the same loan files as
> an `ADMIN`.
>
> The company boundary is the only boundary, and it is absolute: no route exposes
> another company's file, or any child of it, under any identifier.
>
> User attribution *is* recorded — `actor_user_id` on the activity log,
> `uploaded_by_user_id` on documents — so "who did this" is answerable without "who
> may see this" ever being a question.

---

## DATA — 8. The staging rows

The staging database is in a private subnet with no public route and ECS Exec is
off, so this ran as a one-off Fargate task on the migrate task definition
(`mbai-staging-migrate:3`), executing **three SELECTs and nothing else** — no
borrower columns, no writes. Task
`9212de9eba6a455f9a00aaa869f57677`, exit code 0.

```
== companies: 1 row(s)
   id=20370752-7b78-4871-8007-66f7eaa46d70 | slug=mb | name=MortgageBoss | is_active=True | deleted_at=None

== users: 2 row(s)
   id=daaf5120-15aa-4f8b-be88-7ce4843b534e | email=rakheethaker@mortgageboss.ai | company_id=20370752-7b78-4871-8007-66f7eaa46d70 | role=admin | is_active=True | deleted_at=None
   id=877642d4-6e94-4cc6-a75d-7d1c655ed1e5 | email=geetthaker@mortgageboss.ai  | company_id=20370752-7b78-4871-8007-66f7eaa46d70 | role=admin | is_active=True | deleted_at=None

== loan_files: 1 row(s)
   id=8d5081db-7466-4f6c-a842-93ef09760d64 | display_id=LF-4A5V | company_id=20370752-7b78-4871-8007-66f7eaa46d70 | status=draft | deleted_at=None | created_at=2026-08-13 01:09:04.866622+00:00
```

**All three `company_id` values are the same UUID**, `20370752-7b78-4871-8007-66f7eaa46d70`
— company `mb`. Both users are in it, both are `admin`, both active. The one loan
file, `LF-4A5V`, is in it.

The observation is explained completely: the file belongs to `mb`, both users belong
to `mb`, and the reader filters on company. **By design.**

The contradicting outcome flagged before running this — two companies with the users
split across them — did not occur. There is only one company in the environment.

⚠️ **One honest limit of this check.** With a single company in the database, these
rows cannot *demonstrate* the cross-company boundary; there is no company B to be
excluded from. That boundary rests on the code in §§3, 6 and 7 above, plus the
integration tests. This check does exactly one job — it confirms the observed
sharing is same-company sharing — and it does that conclusively.

---

## Summary

| question | answer |
|---|---|
| Scoped to company or user? | **Company.** `company_id` is the only ownership column on `loan_files` |
| Is what you saw correct? | **Yes — by design.** Confirmed in the data: both users and `LF-4A5V` share one `company_id` |
| Any per-user visibility? | **None.** No assignment table, no assignee, no sharing |
| Is the between-company boundary enforced? | **Yes**, on all 81 routes, structurally |
| Unscoped queries reaching tenant tables? | 14, all traced; 13 receive authorized objects or are non-HTTP; 1 is dead code |
| Anything to fix? | `get_document_borrower_links` — unreachable dead code carrying the A2 pattern |
