# Phase 4.5 readiness survey — what exists before Stage 0 and Stage 1

- **Type:** Read-only survey. Nothing built, nothing changed, no model calls, no migrations run.
- **Date:** 2026-09-23
- **Branch:** `phase4.5-conditions`, cut from `phase4-with-ui` at `ce05b79f` (spec §2).
- **Spec:** [`../phases/phase4.5-stage0-1-build-spec.md`](../phases/phase4.5-stage0-1-build-spec.md) §3
  requires this file. **Where the code differs from the spec, the code wins and the difference is
  recorded in §14.**
- **Method:** every name, signature and line reference below was read in this tree on this branch.
  Nothing is carried from the spec's own description or from memory of another branch.

---

## 0. Branch and numbering (spec §2) — verified, no STOP AND ASK

| Check | Result |
|---|---|
| Branch cut from `phase4-with-ui` | `phase4.5-conditions` @ `ce05b79f`, `--no-track`, tree clean |
| `LP-903 … LP-910` free on this branch | yes — highest are LP-902, LP-1000, LP-1001 |
| `LP-903 … LP-910` free on `raspberrypi-work` | yes (checked with `git ls-tree -r raspberrypi-work -- docs/tickets/`) |
| `ADR-403 … ADR-407` free on both | yes — `decisions.md` ends at **ADR-402** (`## ADR-402`, line 16129) |
| Spec + 13 PNGs + 13 HTMLs present on the branch | yes — added by `ce05b79f "Supporting documents"` |
| Working tree clean before starting | yes — nothing to commit, so the spec's "commit them first" step was a no-op |

⚠️ **`phase4-with-ui` does not contain the LP-1000 line of work.** The merge commit `fdbaa3a1`
(raspberrypi-work → phase4-with-ui) was made locally on 2026-09-13 and never pushed; origin has moved
twice since and the local branch was fast-forwarded past it. So **32 commits** — LP-1000 (document
content digest, the partial unique index, the upload race), bug-024…027 and LP-1001 — exist only on
`raspberrypi-work` and `rasp_phase4_5_condition`. This changes one signature Stage 1 depends on (§6),
and it means a later merge of those branches will have to reconcile `services/documents.py`.

---

## 1. Conventions — where code goes, and the ADR format

`CLAUDE.md`, `docs/project-structure.md` and `docs/development-workflow.md` are **byte-identical** on
this branch to the copies read while planning (checked with `git diff`), so their guidance stands.

| To add… | Goes in… |
|---|---|
| model | `backend/app/models/` + an Alembic migration in `backend/alembic/versions/` |
| Pydantic schema | `backend/app/schemas/` |
| API router | `backend/app/api/` |
| business logic | `backend/app/services/` |
| Celery task | `backend/app/tasks/` **and** a line in `_TASK_MODULES` (§9) |
| AI prompt | `backend/app/ai/prompts/<area>/<name>.txt` |
| domain knowledge that is not data | an app-layer module — `app/documents/catalog.py` is the precedent (ADR-400) |
| frontend page | `frontend/app/(protected)/…` |
| frontend API hook | `frontend/lib/api/<area>.ts` |
| frontend shared type | `frontend/lib/types/<area>.ts` |
| ticket record | `docs/tickets/LP-XXX.md` (required for every ticket) |
| architecture decision | a new ADR in `decisions.md` |

**There is no `backend/app/conditions/` package and no condition code of any kind** — greps for
`ConditionRound` / `condition_round` across `app/` return nothing. Stage 1 starts on empty ground.

**ADR format**, from the last ten (ADR-393 … ADR-402): a `## ADR-NNN` heading, a bold one-sentence
statement of the decision, then italic `*Context.*` / `*Decision.*` / `*Rationale.*` /
`*Consequences.*` / `*Status.*` paragraphs. `*Status.*` reads `Accepted (LP-NNN)` and names what it
extends or amends. Several also carry a `*Corrected in review.*` paragraph — corrections are written
into the ADR rather than replacing what was there.

---

## 2. Base model, mixins and scoping

`app/models/base.py` (92 lines):

| Name | What it adds |
|---|---|
| `Base(DeclarativeBase)` | `MetaData` with `NAMING_CONVENTION` (`ix_`, `uq_`, `ck_`, `fk_`, `pk_`) — constraint names are predictable, which the activity-type guard in §13 relies on |
| `UUIDMixin` | `id: Mapped[UUID]`, `primary_key=True`, `default=uuid4` |
| `TimestampMixin` | `created_at`, `updated_at` — both `DateTime(timezone=True)`, `default=utcnow`, `updated_at` also `onupdate=utcnow` |
| `SoftDeleteMixin` | `deleted_at: Mapped[datetime \| None]` + an `is_deleted` property. **Filtering is explicit, never global.** |
| `utcnow()` | the timezone-aware now used as every default |

`app/models/helpers.py` (78 lines) — the two filters every query composes:

```python
only_active(stmt, Model)                      # WHERE deleted_at IS NULL
scope_to_company(stmt, Model, company_id)     # WHERE company_id = :company_id
```

`app/models/types.py` — `SHORT_STRING=64`, `MEDIUM_STRING=256`, `LONG_STRING=1024`, and the annotated
aliases `ShortStr`, `MediumStr`, `LongStr`, `Money` (`Numeric(14, 2)`, always `Decimal`).

`app/models/enums.py` — **the string-enum convention, and it matters for every enum Stage 1 adds:**

```python
str_enum(enum_cls, *, length: int = 32, name: str | None = None) -> SAEnum
```

`native_enum=False` + `create_constraint=True` → the column is a bounded `VARCHAR` with a **CHECK
constraint**, not a PostgreSQL `ENUM` (ADR-037). Adding a value needs no `ALTER TYPE` — but it does
need a **constraint-swap migration**, and for `activity_type` that is guarded by three tests (§13).
Pass `name=` when one enum backs two columns on a table, or the constraint names collide.

**How Stage 1 uses it:** every model in LP-904 is `Base, UUIDMixin, TimestampMixin, SoftDeleteMixin`
except `condition_events` (§3). Every enum column goes through `str_enum`. Every query gets
`scope_to_company` + `only_active`.

---

## 3. Append-only precedent — the model exists, **the test does not**

`app/models/finding_event.py` (79 lines) is the pattern the spec names, and it is enforced **by
shape**:

```python
class FindingEvent(Base, UUIDMixin):          # ← no TimestampMixin, no SoftDeleteMixin
    __tablename__ = "finding_events"
    __table_args__ = (Index("ix_finding_events_finding_occurred", "finding_id", "occurred_at"),)
    finding_id:  Mapped[UUID]        = mapped_column(ForeignKey("findings.id", ondelete="CASCADE"))
    event_type:  Mapped[FindingEventType] = mapped_column(str_enum(FindingEventType))
    from_outcome / to_outcome        = str_enum(EvaluationOutcome, name="finding_event_from_outcome")
    detail:      Mapped[dict]        = mapped_column(JSONB, default=dict)   # "PII-safe … never raw borrower data"
    occurred_at: Mapped[datetime]    = mapped_column(DateTime(timezone=True), default=utcnow)
```

Its own docstring states the rule: *"Append-only: insert-only, no `updated_at` and no soft-delete (a
`TimestampMixin` would add `updated_at`; a `SoftDeleteMixin` would allow a mutating delete)."*

⚠️ **The spec says to copy "`models/finding_event.py` **and its tests**". There are no such tests.**
Every hit for `FindingEvent` under `tests/` only *reads* event rows to assert a lifecycle sequence —
`tests/services/test_finding_reconcile_runs.py:86` (`_events`) and
`tests/services/test_unidentified_document_lifecycle_lp640.py:103` (`_event_types`). Nothing asserts
that an event cannot be updated or deleted.

**How Stage 1 uses it:** `condition_events` copies the model shape exactly — `Base, UUIDMixin` only,
`occurred_at`, JSONB `detail`. LP-904's done-when ("an append-only test shows `condition_events`
cannot be updated or deleted through the service layer") has **nothing to copy and must be written
from scratch**: the service layer exposes only an append, and the guard asserts there is no update or
delete path. Two notes carried from the model: `detail` here is declared **NPI** by the spec (unlike
`FindingEvent.detail`, which is explicitly PII-safe), so it is excluded from the readonly view; and
`condition_events` needs `company_id` because it is reached directly, where `FindingEvent` is reached
through its finding.

---

## 4. Encryption, NPI and the `readonly.*` views (ADR-405)

**Column-level encryption exists but is the wrong tool here.** `app/models/encrypted_types.py` gives
`EncryptedString` (a `TypeDecorator` over `Text`, Fernet, via `app.core.encryption`). Its own docstring
rules it out for condition text: *"encryption is non-deterministic … an encrypted column CANNOT be
used in a SQL `WHERE` equality, `ORDER BY`, index, or unique constraint."* Condition text is diffed,
searched and fingerprinted, so ADR-405's "ordinary queryable columns protected by storage-level
encryption and TLS, excluded from the readonly views" is the correct reading and matches how
`documents.full_text` is handled.

**The exclusion mechanism** (`docs/querying-staging.md`): the `mbai_readonly` role has **no privileges
in schema `public`**; it can read only `readonly.*` views, which drop a column entirely or pass it
through `readonly.scrub()` (shape-matching, not a key denylist). `documents.full_text`,
`findings.source_snippet`, `communications.body`, `loan_files.inbox_token` and
`lenders.contact_email` are among those dropped outright — the precedent for every NPI column Stage 1
adds.

**How a view is declared** (`alembic/versions/20260908_0100_c9d3a71b8e52_lp806_triage.py`): `DROP VIEW
IF EXISTS readonly.x` then `CREATE VIEW readonly.x AS SELECT <explicit column list> FROM public.x`,
with a conditional `GRANT` guarded by `IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname =
'mbai_readonly')`. Two hazards that migration records in its own words, both of which apply to LP-904:

- a rebuild is where columns **silently disappear** — its first cut copied a `CREATE VIEW` from an
  earlier migration's **downgrade** block and dropped three columns;
- `tests/test_readonly_query.py` reads the migration **as text** and only the half **above
  `def downgrade(`** describes the live database, so view SQL must stay inside the function that runs
  it and never be hoisted to a module constant.

C7 also exposes `drop_readonly_schema()` / `create_readonly_schema()` for migrations that must alter a
column a view depends on.

**How Stage 1 uses it:** LP-904 adds `readonly.condition_rounds`, `readonly.conditions`,
`readonly.condition_events` and `readonly.lender_condition_codes`, dropping every column the spec
marks NPI — `raw_text`, `header`, `draft_rows`, `parse_report.unassigned_lines`, `verbatim_text`,
`underwriter_notes`, `condition_events.detail`. `expiry_dates` and `text_fingerprint` are **not** NPI
and stay.

---

## 5. Loan file and lender

**`LoanFile`** (`app/models/loan_file.py`, 410 lines) — `Base, UUIDMixin, TimestampMixin,
SoftDeleteMixin`, with `company_id` (:169), `lender_id` nullable (:175), `legal_hold` +
`legal_hold_at` + `legal_hold_reason` (:191-195), `inbox_token` (:164) and a lowercase functional
index `ix_loan_files_inbox_token_lower` (:154).

```python
def get_inbox_address(self) -> str:          # :367
    return f"lf-{self.inbox_token}@{domain}"  # :407
```

ADR-397: the **address** is exposed, the raw `inbox_token` field never is — and the address *contains*
the token, so it is a bearer credential. S1-01 shows the address; it must come from this accessor.

**`Lender`** (83 lines) — `company_id` FK (`ondelete="RESTRICT"`) and
`UniqueConstraint("company_id", "slug")`. **So lenders are company-scoped: the slug is unique per
company, not globally** (ADR-045). Fields: `name`, `slug`, `contact_email`, `portal_url`,
`contact_phone`, `notes`, `lender_overlays` (JSON), `supported_programs` (JSON), `is_active`.

**`LenderContact`** (87 lines) — `lender_id`, `name`, `email`, `phone`, `role` (`LenderContactRole`),
`notes`, `is_active`.

**How Stage 1 uses it:** LP-904 adds `mortgagee_clause`, `condition_upload_cutoff` and
`condition_handling_notes` to `lenders`. `lender_condition_codes` is scoped the way `lenders` is —
i.e. reached through a company-scoped lender, so a `(lender_id, code)` unique constraint is already
per-company by construction. ⚠️ **The company-scoping of `lenders` is what makes LP-910's seeding a
STOP AND ASK — see §15.**

---

## 6. Documents and storage

**`StorageBackend`** (`app/storage/base.py`, 124 lines) — abstract, obtained via
`get_storage_backend()`:

```python
await storage.save(*, company_id, file_id, document_id, filename, content) -> str   # path
await storage.save_at(*, storage_path, content) -> str    # bytes with no tenant (inbound .eml)
await storage.read(storage_path) -> bytes
await storage.delete(storage_path) -> None
await storage.get_url(storage_path) -> str | None
```

`build_storage_path(company_id, file_id, document_id, filename)` →
`{company_id}/{file_id}/{document_id}.{ext}`; only the extension derives from the filename and it is
allowlisted (`ALLOWED_EXTENSIONS`, fallback `bin`).

**`create_document`** (`app/services/documents.py:125`) — **on this branch**:

```python
async def create_document(db, *, loan_file, document_id, filename, mime_type, size,
                          storage_path, uploaded_by_user_id,
                          upload_source: UploadSource = UploadSource.USER_UPLOAD) -> Document
```

It creates a `PENDING` row, `flush()`es, and calls `mark_verification_stale`. ⚠️ **There is no
`content` parameter and no duplicate check** — `content_sha256`, `content_digest` and `find_duplicate`
do not exist here (they are LP-1000, absent per §0).

**`Document`** (338 lines) — owned child of the loan file, **no `company_id`** (ADR-052).
`DocumentStatus`: `PENDING → CLASSIFYING → CLASSIFIED → EXTRACTING → COMPLETED`, plus `FAILED`,
`NEEDS_REVIEW`. `UploadSource`: `USER_UPLOAD`, `BORROWER_INBOX`, `MISMO_IMPORT`, and an upload-link
value. `document_type` is a flexible indexed string, deliberately not an enum (ADR-053).

**The upload route** (`app/api/documents.py:318`) is the shape LP-905 mirrors — two stages, so an
invalid file in a batch persists nothing:

1. `_read_capped(upload_file, max_bytes=MAX_FILE_SIZE_BYTES)` (:298 — chunked, aborts past the cap)
   then `validate_upload(content=…, declared_content_type=…)`, which checks size, an allowlist
   (`application/pdf`, `image/jpeg`, `image/png`) **and** the magic bytes against the declared type;
2. `storage.save(...)` → `create_document(...)` → one `log_activity(...)` → `db.commit()` → per-document
   fire-and-forget `_enqueue_processing()` **after** the commit.

⚠️ `MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024` is a **module constant** in `services/documents.py:56`,
not a setting. The spec asks for "size limit from settings (default 20 MB)" — see §14.

**How Stage 1 uses it:** LP-905 stores the sheet with `storage.save_at()` under a
server-built path, **not** as a `Document`, so it never enters classify → extract → needs. That
avoids the spec's STOP AND ASK entirely (§15).

---

## 7. PDF, rasterize and OCR — LP-906's foundation, and it is already here

**Installed** (`pyproject.toml`): `pypdf>=5.1.0`, **`pymupdf>=1.27.2.3`**, `pikepdf>=10.13.0.post1`.
`pdf_utils.py` and `page_render.py` both `import pymupdf`.

**Word positions exist today.** `app/services/page_ocr.py`:

```python
def has_native_words(page: pymupdf.Page) -> bool          # :118 — per PAGE, never per document
def words_for(page, budget=None) -> list[tuple[float, float, float, float, str]]   # :129
def ocr_words(page) -> list[tuple[float, float, float, float, str]]                # :189
def ocr_available() -> bool                                                        # :100 (cached)
```

`words_for` returns `(x0, y0, x1, y1, word)` **in point space**, using the page's own text layer where
it has one and OCR where it does not — the same tuple shape either way, so a caller never branches on
which kind of page it is.

**➜ LP-906 needs no new runtime dependency, so spec §6's STOP AND ASK on adding a PDF library does not
trigger.** `Line.y` / `Token.x0` come straight from these tuples; grouping words into lines by `y` is
the only new code.

Also available: `pdf_utils.extract_text_from_pdf(content) -> PdfTextExtractionResult`,
`pdf_page_count`, `first_n_pages`, `cap_pdf_pages`, `fit_pdf_to_payload_budget`;
`page_render.render_page(...)` with `DEFAULT_ZOOM = 2.0`, `RENDERABLE_TYPES`, `TEXT_SEARCHABLE_TYPES =
{"application/pdf"}`; and `attachment_safety.assess(data, declared_content_type=…) -> SafetyOutcome`,
`sniff_content_type`, `is_encrypted_pdf`, `sanitise_pdf`, `rasterise_pdf`, `render_preview_png`, with
`MAX_PAGES = 200`.

**How Stage 1 uses it:** LP-905 sniffs and sanitises through `attachment_safety` before storing.
LP-906 builds `Line`/`Token` from `words_for`. LP-908 rasterises with `rasterise_pdf` and OCRs, and
**never** sends the PDF's raw text layer to a model.

---

## 8. Inbound email and `CORRESPONDENCE`

**`AttachmentDisposition`** (`app/models/inbound_attachment.py:46`): `PENDING`, `ACCEPTED`,
**`CORRESPONDENCE`** (:58), `REJECTED`, `DUPLICATE`. `AttachmentSafetyState`: `PENDING`, `SAFE`,
`QUARANTINED`, `UNSUPPORTED` — and `PENDING` is explicitly *not* a pass.

**`accept_attachment`** (`app/services/inbound_triage.py:130`) refuses unless the attachment is `SAFE`
**and** its disposition is still `PENDING`, and refuses cross-file attachments. Its
`AcceptAs.CORRESPONDENCE` branch (:169) **only sets the disposition and logs
`COMMUNICATION_RECEIVED`** — it stores nothing, creates no `Document`, and returns
`AcceptResult(attachment, None, …)`.

**Are the bytes still retrievable? Yes — from the raw message.** `_attachment_bytes` (:70) reads the
`.eml` from `message.raw_storage_path` via `storage.read()`, re-parses it, and matches the part back
**by sha256**. It raises `CannotAcceptError` in two cases: the message is gone
(`"The original message is no longer available."`) or no part hashes to what was recorded
(`"The attachment no longer matches the stored message."`).

**➜ Spec LP-905's STOP AND ASK ("if `CORRESPONDENCE` does not keep the file retrievable") does not
trigger.** Two consequences for the build, both real:

- `_attachment_bytes` is **private**. LP-905 needs a public wrapper or an export; re-implementing the
  sha256 match would be a second answer to one question.
- because `accept_attachment` refuses a non-`PENDING` disposition, "Use as condition sheet" cannot go
  through it for an attachment already filed as correspondence. The spec's separate route
  `POST /api/inbound/attachments/{id}/condition-round` is therefore right, and it must keep the
  `CORRESPONDENCE` disposition rather than move it.

**`InboundMessage`** (152 lines): `company_id` and `loan_file_id` both **nullable**, `raw_storage_path`,
`from_address`, `to_addresses`, `subject`, `received_at`, `auth_verdicts`, `routing_state`
(`InboundRoutingState`), `routing_signal`, `routing_confidence`, `is_dsn`/`is_auto_reply`/`is_bulk`.
Nullable routing is why the spec's condition-round route accepts `loan_file_id` in the body when the
message is unrouted.

**API** (`app/api/inbound.py`, 267 lines): `GET /messages` (:141), a preview route (:170),
`POST /attachments/{attachment_id}/accept` (:217, with `as_correspondence` selecting the branch), and
`POST /attachments/{attachment_id}/reject` (:247).

---

## 9. Tasks, sessions and the per-file lock

`app/tasks/base.py`:

- `run_async(coro)` — a **fresh event loop per task** (`asyncio.run`), and the boundary where the
  cached AI client is closed. Safe only because the worker pool is prefork.
- `task_session()` — an async context manager yielding an `AsyncSession` on a **fresh engine created
  inside the current loop**, `NullPool`, disposed at the end. The app's module-level engine must not
  be reused across task loops.

`app/tasks/celery_app.py` — ⚠️ **`_TASK_MODULES` (:25-31) is an explicit list**, and its comment says
*"EVERY module under `app/tasks/` that defines a `@celery_app.task` MUST be listed here, or the worker
never imports it and the task is unregistered — enqueued messages are silently [dropped]"*. **LP-905
must add `"app.tasks.conditions"`.**

`app/tasks/retry.py` — `MAX_RETRIES = 3`, `retry_countdown(retries)`, and

```python
retry_or_terminal(self, fn, *, on_exhausted=…, event=…, terminal_on: tuple[type[BaseException], ...] = ())
```

`terminal_on` exceptions are never retried. This is how spec §9's "typed errors with the real reason"
is expressed in this codebase.

**The per-file lock** is `loan_file_needs_lock` in `app/services/needs_engine.py` (not in `tasks/`):
a Redis lock keyed `needs-lock:{loan_file_id}`, `@asynccontextmanager`, yielding **whether it was
acquired** — the caller proceeds either way — with a `timeout` so a crashed worker cannot deadlock the
file. Usage pattern from `tasks/needs.py:72`:

```python
async with loan_file_needs_lock(loan_file_id), task_session() as db:
    ...
    await db.commit()
```

**How Stage 1 uses it:** `tasks/conditions.py::parse_condition_round` follows exactly this shape.
LP-909's import runs inside `loan_file_needs_lock` in one transaction, as the spec requires — noting
that the lock is **advisory**, so it serialises the common case and is not mutual exclusion.

---

## 10. AI

```python
# app/ai/client.py:554
async def complete(*, model: str, messages: list[dict], max_tokens: int,
                   system: str | None = None, temperature: float | None = None) -> AICompletion

@dataclass(frozen=True)                       # :78
class AICompletion:
    text: str; input_tokens: int; output_tokens: int; model: str
    stop_reason: str | None = None
    cache_read_tokens: int = 0; cache_write_tokens: int = 0
    @property
    def billed_input_tokens(self) -> int
```

- **Prompts:** `load_prompt("area/name.txt")` (`app/ai/prompt_loader.py:19`) — `@cache`d, path-checked
  against escape. Every existing prompt is a **`.txt`** under `app/ai/prompts/<area>/`
  (`classification`, `extraction`, `needs`, `analysis`, `summarization`, `communication`).
- **Cost:** `estimate_cost(*, model, input_tokens, output_tokens, cache_read_tokens=0,
  cache_write_tokens=0)` (`app/ai/cost.py:61`). Existing callers:
  `tasks/document_processing.py:706`, `services/tag_production.py:342`, `dev/bench/engine.py:312`.
- **Model ids are settings, never literals:** `settings.anthropic_model_classification` /
  `_extraction` / `_reasoning` / `_analysis` (`app/core/config.py:121-135`), with
  `bedrock_model_*` counterparts resolved inside `complete()` so no caller knows the provider.
  **LP-908 uses the extraction tier: `settings.anthropic_model_extraction`.**
- **Rate limiting:** `get_rate_limiter()` (`app/ai/rate_limit.py:120`) — applied per attempt inside
  `complete()`, so callers do nothing.

⚠️ The spec names `ai/prompts/conditions/split_v1.md`; the repo convention is `.txt` (§14).

---

## 11. Activity and timeline

**`ActivityType`** (`app/models/activity_log.py:39`) is a `StrEnum` stored as VARCHAR + CHECK named
`ck_activity_logs_activitytype`. It already carries `DOCUMENT_UPLOADED`, `COMMUNICATION_RECEIVED`,
`DOCUMENT_REPROCESSED`, the needs and DTI families, and so on.

```python
await log_activity(db, *, loan_file_id, activity_type, summary,
                   actor_user_id=None, detail=None) -> ActivityLog     # services/activity_log.py:68
```

`flush()` only — the caller owns the transaction. Helpers: `audit_value()` (JSON-safe, exact for
`Decimal`) and `field_changes(before, after)`. `list_recent_activity(db, *, loan_file_id, limit=20)`
feeds the file rail's "Recent activity" that S1-02 and S1-05 show.

⚠️ **Adding an `ActivityType` value requires a constraint-swap migration, and three tests enforce how**
(`tests/test_activity_type_migrations.py`, 317 lines — see §13).

**Timeline** (`app/services/timeline.py`, 606 lines): `build_timeline` (:482) assembles
`TimelineEntry` (:120) rows filtered by `TimelineFilter`, with `TimelineKind`, `TimelineAttachment`
and a `_summarise` step. Stage 1 does not change it; the "Condition sheet received" entry is an
`ActivityLog` row, which the file rail already renders.

---

## 12. Frontend

**The Conditions tab is a placeholder today** —
`frontend/app/(protected)/loan-files/[id]/conditions/page.tsx` renders `<TabPlaceholder title="Conditions"
phase="Phase 4.5" … icon={ListChecks} />`. Sibling tabs: `communication`, `documents`, `needs`,
`review`, `verification`, `lender-package`. The shell is `[id]/layout.tsx` — a client component that
fetches the file once and renders `FileHeader` + tab nav + `FileContextRail`, with each tab a page
rendered into `{children}`. **The Conditions tab only changes the work surface**, which is exactly what
the design README requires.

**API hook pattern** (`lib/api/needs.ts` is representative): TanStack Query over `apiClient`, a
`const API_V1 = "/api/v1"`, exported `…QueryKey(fileId)` factories, a path builder, `useQuery` /
`useMutation` with explicit invalidation, and a `noRetryOn404` guard. Types live in
`lib/types/<area>.ts`. **LP-909 adds `lib/api/conditions.ts` + `lib/types/condition.ts`.**

**Components available** (`components/ui/`): `badge`, `button`, `card`, `dialog`, `dropdown-menu`,
`empty-state`, `error-state`, `form`, `input`, `label`, `searchable-select`, `select`, `separator`,
`sheet`, `skeleton`, `spinner`, `table`, `textarea`, `tooltip`. Plus `components/status-token.tsx`.

- **`EmptyState`** takes `kind: "nothing-yet" | "filtered" | "structural"` — S1-01 is **`nothing-yet`**
  ("the list is real and has no rows; say what goes here and offer the ONE action that fills it").
- **`Sheet`** exports `Sheet, SheetTrigger, SheetClose, SheetContent, SheetHeader, SheetTitle,
  SheetDescription` — S1-09's round-details panel.
- **`StatusToken`** is the Ledger's one way to show a status: colour **+** glyph **+** word, never
  colour alone; `lib/status.ts` holds per-enum `StatusMeta` maps and `resolveStatus`. Stage 1 shows no
  condition status at all, so no new map is added.

**Tokens** (`app/globals.css`, ADR-402): roles point into a palette. `--primary: var(--brand)`,
`--warning: var(--amber)`, and **`--ai: var(--violet)` with `--ai-foreground` (:62-63)** — the token
the design README requires for AI-marked rows. Radius is split: `--radius` 5px controls,
`--radius-container` 8px panels. **`font-serif` → `var(--font-plex-serif)`** in
`tailwind.config.ts:81` — the face for the lender's quoted wording. No component may name a palette
colour or a hex value; `palettes.test.ts` enforces it.

**Inbound triage UI** for S1-13: `components/file/communication/inbound-attachment.tsx`,
`inbound-message-card.tsx`, `inbound-messages-panel.tsx`, and `app/(protected)/inbound/page.tsx`.

---

## 13. Tests, types and CI

| Gate | Command | Notes |
|---|---|---|
| lint | `uv run ruff check .` | |
| format | `uv run ruff format --check .` | |
| types | `uv run mypy app/` | `strict = true`, `warn_return_any`, Python 3.12 (`pyproject.toml:72`). **`app/` only — `tests/` is not type-checked.** |
| backend tests | `uv run pytest -v` | `testpaths = ["tests"]`, `asyncio_mode = "auto"` |
| frontend | `pnpm lint`, `pnpm typecheck`, `CI=true TZ=UTC pnpm test`, `pnpm build` | |

**`db_session`** (`tests/conftest.py:169`) is function-scoped: a dedicated connection, a transaction,
an `AsyncSession` bound to it, **rolled back** afterwards. Tests `flush()`, never `commit()`. Autouse
fixtures pin the inbox domain to a `.test` name and pin the AI provider.

**Test layout:** `tests/{api,services,models,tasks,ai,documents,storage,integration,verification,…}`.
Fixtures build their own `Company` / `Lender` inline with `uuid4()`-suffixed slugs
(`tests/services/test_overlay_update_audit.py` is the shape to copy). A dedicated
`tests/models/test_tenant_isolation.py` exists.

**Guards Stage 1 must satisfy:**

- **`tests/test_alembic_single_head.py`** — exactly one migration head. The true head on this branch
  is **`c9e4a7b12d36`** (`20260913_0200_c9e4a7b12d36_lp855_mail_client.py`); it is the only revision
  referenced by a single file, the other four candidates being merge-migration artifacts. LP-904
  chains onto it. Naming convention: `YYYYMMDD_HHMM_<revision>_<slug>.py`.
- **`tests/test_activity_type_migrations.py`** — three assertions, parsed from migration **text** with
  `ast` (the suite's `create_all` schema regenerates the CHECK from the enum, so a database test
  cannot see this): every `ActivityType` value is permitted by some swap; **at least one swap lists
  the whole enum**; and parallel (unmerged) lineages must permit **identical** sets, because a swap
  drops and recreates the constraint from its own tuple.
- **`tests/test_readonly_query.py`** — reads view SQL from the migrations as text, above
  `def downgrade(` only (see §4).
- **`tests/test_unwired_services.py`** — worth knowing before adding services nothing calls yet.

**One enum value Stage 1 and Stage 3 do *not* have to add** (found during LP-903's review):
`NeedsItemOrigin.CONDITION = "condition"` already exists at `app/models/needs_item.py:91`, reserved
for this phase, with **zero branches on it** in `backend/app/`. Crucially its value is **already in
the stored constraint** — present in the original `create_needs_items` migration
(`20260611_1003_4db01a03523e:69`) and again in the LP-68 swap
(`20260619_1600_93a861456e2f:46`, `_ORIGIN_OLD = ("manual", "finding", "condition", "template")`). So
when Stage 3 creates needs from conditions it needs **no constraint-swap migration** for the origin.
Checked rather than assumed, because the reverse case — an enum member the CHECK does not permit — is
the exact defect `test_activity_type_migrations.py` was written for.

---

## 14. Differences from the spec — what the code says instead

The spec's own rule: *"the survey is the source of truth; where the code differs, follow the code."*
These are the differences that change what gets written.

| # | Spec says | The code says | What Stage 1 does |
|---|---|---|---|
| 1 | copy `finding_event.py` **and its tests** | the model exists; **no immutability test exists anywhere** | write LP-904's append-only guard from scratch (§3) |
| 2 | upload "size limit from settings (default 20 MB)" | `MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024`, a module constant in `services/documents.py:56` | add a `condition_sheet_max_bytes` setting defaulting to 20 MB rather than reusing the 50 MB constant, and record it in LP-905 |
| 3 | prompt at `ai/prompts/conditions/split_v1.md` | every prompt is a **`.txt`** under `app/ai/prompts/<area>/` | `app/ai/prompts/conditions/split_v1.txt` |
| 4 | "reuse the attachment safety service" | `attachment_safety.assess()` is sync and returns `SafetyOutcome`; the private `_attachment_bytes` is the only byte-retrieval path for a forwarded attachment | LP-905 exports a public wrapper rather than duplicating the sha256 match (§8) |
| 5 | `condition_events` copies `FindingEvent` | `FindingEvent` has no `company_id` (reached through its finding) and its `detail` is declared **PII-safe** | `condition_events` carries `company_id` **and** its `detail` is NPI → dropped from the readonly view |
| 6 | `lender_condition_codes` "scope it the way `lenders` is scoped" | `lenders` is **company-scoped** with `UniqueConstraint(company_id, slug)` | `(lender_id, code)` unique is per-company by construction — but see §15.1 |
| 7 | — | `create_document` has **no `content` parameter** on this branch (LP-1000 is absent) | LP-905 stores the sheet via `storage.save_at()` and never creates a `Document` |

---

## 15. STOP AND ASK — three cleared, one raised

**Cleared by measurement, with the evidence:**

| Spec point | Verdict |
|---|---|
| §6 LP-906 — "STOP AND ASK if [a PDF library] would be a new runtime dependency" | **No stop.** `pymupdf>=1.27.2.3` is installed and `page_ocr.words_for()` already returns word rectangles in point space (§7). |
| §6 LP-905 — "STOP AND ASK if the only way to store it would send it through classify → extract → needs" | **No stop.** `storage.save_at()` exists precisely for bytes that are not a document (§6), so the sheet is stored without a `Document` row. |
| §6 LP-905 — "STOP AND ASK if `CORRESPONDENCE` does not keep the file retrievable" | **No stop.** `_attachment_bytes` re-derives the bytes from the stored `.eml` and matches by sha256 (§8). Two typed failure modes must be handled, not assumed away. |

⚠️ **15.1 — Raised, and it will block LP-910.** The spec says to seed the UWM and Champions code maps
by "match[ing] by lender name/slug; **STOP AND ASK** if there is no reliable way to identify UWM and
Champions". **There is no reliable way.** `lenders` is company-scoped with a slug unique only *per
company* (ADR-045, `uq_lenders_company_id_slug`), chosen by each processing company — so "UWM" may be
`uwm`, `uwm-wholesale`, `united-wholesale` or absent entirely, and two companies' UWM rows are two
different `lender_id`s. A seed keyed on a slug will silently match nothing on some tenants and the
wrong row on others.

Three options were put to the product owner:

1. a nullable `canonical_lender_key` (e.g. `"uwm"`, `"champions"`) on `lenders`, set by an admin, with
   the seed keyed on it — explicit, one column, and the code map becomes reusable across tenants;
2. seed per company for lenders whose slug matches a known pattern, and report the ones it skipped;
3. ship the YAML files and a loader with **no** seeding, leaving every `(lender, code)` to arrive as
   `OBSERVED_UNMAPPED` on first import — the spec's own fallback for unknown codes.

✅ **ANSWERED 2026-09-23 — option 1.** A nullable `canonical_lender_key` on `lenders`, admin-set, and
the LP-910 seed matches on it. **Consequence for the build order:** the column is a `lenders` column,
so it is added in **LP-904's** migration beside `mortgagee_clause`, `condition_upload_cutoff` and
`condition_handling_notes` — not deferred to LP-910, which only reads it. A lender with the key unset
is not an error: its codes arrive as `OBSERVED_UNMAPPED`, which is option 3's behaviour retained as
the fallback rather than replaced.

**Note also:** LP-903's vocabulary lands in an existing section — `docs/glossary.md` already has a
`### Conditions` heading (line 88) under "Domain Terms". The new terms extend it rather than starting
a new section.

### 15.2 — The UI tickets' "Visual check": answered, and it is a real limit

`docs/design/phase4.5-conditions/README.md` says to build a screen, **run the app**, open that state
with fixture data at 1600 px, screenshot it, and compare against the PNG. Two things make that
impossible from this session, both measured rather than assumed:

- **The app cannot run here.** No local Postgres and no Docker — the same gap that leaves LP-904's
  migration unexecuted and every DB-backed test collect-only.
- **There is no browser driver, and adding one is forbidden by the README** ("the repo has no
  Playwright, so don't add one just for this"). LP-859 independently measured the same absence.

✅ **ANSWERED 2026-09-23 — "the way LP-859".** LP-905, LP-907 and LP-909 carry their **Visual check**
sections marked **UNVERIFIED ON SCREEN**, with the blockers named, exactly as LP-859 §2 and §5 did.
What *is* done for each screen: build it to the PNG (which is readable from here — the PNGs open
directly), and work through its *Must match* list item by item against the built component, recording
each result. What is **not** done is the screenshot-beside-PNG comparison.

This matters because LP-859 is the ticket that established the rule it is being applied to: *"a
ticket that changes what a screen looks like is not done on green CI. Either a browser-level check
runs, or a person looks."* Under this answer, **a person looks** — the product owner, when the three
screens land — and the tickets say so plainly instead of implying CI covered it.

---

## 16. Summary — what Stage 1 can build on, unchanged

| Need | Exists? |
|---|---|
| mixins, company scoping, soft delete, string enums | ✅ §2 |
| append-only model pattern | ✅ model, ❌ test (§3) |
| NPI exclusion mechanism for staging views | ✅ §4 |
| loan file with `lender_id`, `legal_hold`, inbox address | ✅ §5 |
| storage for bytes that are not a `Document` | ✅ `save_at` (§6) |
| PDF word positions without a new dependency | ✅ §7 |
| rasterize + OCR for the AI path | ✅ §7 |
| forwarded-attachment bytes, retrievable | ✅ §8 |
| task session, per-file lock, typed retry | ✅ §9 |
| AI client, prompt loader, cost, tier settings | ✅ §10 |
| activity + timeline | ✅ §11 (a CHECK-swap migration is required) |
| Conditions tab, Ledger tokens, `--ai`, serif, EmptyState, Sheet, StatusToken | ✅ §12 |
| condition models, readers, API, UI | ❌ nothing exists — Stage 1 builds all of it |

## 17. How this was checked

Every file named in spec §3 was opened or grepped on this branch; line numbers above are from those
reads. No database was touched, no migration was run, no model was called, and staging was not
queried. Counts of files and lines come from `wc -l` and `git ls-tree`; the Alembic head was computed
by set-differencing every `revision` against every `down_revision` and then confirming which candidate
is referenced by exactly one file.
