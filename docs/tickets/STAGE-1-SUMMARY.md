# Stage 1 — The per-run verification snapshot (LP-201 … LP-210)

**Status: complete.** Stage 1 builds, freezes, and durably persists an **immutable,
per-run fact snapshot** for a loan file — the input a future rule engine (Stage 2+)
evaluates. It reads already-parsed/extracted data; it does not parse, extract, or
run rules.

## What Stage 1 delivers

A frozen three-section `Snapshot` (one immutable JSONB row per run), PII-safe at
rest, with full provenance and append-only history:

- **`mismo`** — the parsed 1003/MISMO data flattened to a stable dotted-key map
  (`borrower.1.income.1.monthly_amount`, `loan.amount`, `liability.3.…`), each value
  a `Field` (or masked `PiiField`). `source=parsed`, `confidence=null` (deterministic
  parse never fabricates one).
- **`documents`** — one entry per active document: its type, its **resolved
  borrower(s)** (`belongs_to`, from the LP-202 links, joint-capable, `None` when
  unresolved), and its extracted `fields` carrying LP-201's per-field confidence
  faithfully. The raw asserted name stays in `fields.asserted_name`, distinct from
  the resolved reference.
- **`calculations`** — DTI / LTV / MI / reserves, each `{value, breakdown}` with the
  calculator's own per-line source tag (`stated`/`computed`/`extracted`/`manual`/
  `override`) preserved. Not-computable → `None`, never a fabricated 0.

Cross-cutting guarantees, proven end to end (LP-210):

- **PII-safe:** SSNs/account numbers/tax-ids never stored raw — only a masked
  `display` + a per-loan-file, app-secret-keyed `match_hash`. A write-time guard
  refuses to persist a snapshot containing raw PII.
- **Cross-source matching without raw values:** the same raw value in two sections
  (e.g. a borrower's SSN in MISMO and on their W-2) yields the **same `match_hash`**,
  so a rule can match them without ever seeing the raw value.
- **Absent ≠ empty:** "no source supplied this" is structurally distinct from
  "supplied null/empty," at field *and* section level, preserved through JSON + DB.
- **Confidence honesty:** a confidence is a real number or `null` — never a
  fabricated default.
- **Immutable + append-only:** one row per run, insert-only, no update path — a new
  run is a new row, so a processor can jump back to any previous run's state.
- **Resilient + honest build:** one section failing (assembler raises) yields an
  absent-with-reason section, not a lost snapshot.

## In scope / out of scope (Stage 1)

**In:** the three-section frozen model; the Field/PiiField primitives + PII mask/hash;
per-field extraction confidence plumbing; deterministic document→borrower matching +
link storage; the three assemblers; the builder; immutable persistence + PII-at-rest
guard; the e2e test + real-file artifact.

**Out (later stages):** the viewer/UI; running verification *rules* against the
snapshot; triggering builds from the pipeline; reconciling stated-vs-extracted
disagreements (a rule's job); cross-snapshot querying / history-browsing UI.

## Tickets

| Ticket | Delivered | ADR |
|---|---|---|
| LP-201 | Per-field extraction confidence (nullable, honest) | ADR-238 |
| LP-202 | Deterministic document→borrower name matching + link table | ADR-239 |
| LP-203 | `Field`/`PiiField` primitives + keyed PII mask/hash | ADR-240 |
| LP-204 | Frozen three-section `Snapshot` container | ADR-241 |
| LP-205 | MISMO section assembler | ADR-242 |
| LP-206 | Documents section assembler (option-2 belongsTo) | ADR-243 |
| LP-207 | Calculations section assembler | ADR-244 |
| LP-208 | Builder / orchestrator (resilient + honest) | ADR-245 |
| LP-209 | Immutable per-run persistence + PII-at-rest guard | ADR-246 |
| LP-210 | End-to-end test + real-file validation | — (validation) |

## Deferred items & known gaps (collected from LP-201…210)

**Pipeline wiring**
- **The LP-202 matcher is not wired into document processing.** Links are populated
  only by an explicit call to the matcher service, so on an un-matched file
  `belongs_to` is `None` everywhere. (Surfaced by LP-210 on LF-6T3N — 0 links.) Owner:
  a future "wire the matcher" ticket.
- **The snapshot builder is not triggered by anything.** `build_snapshot` is a library
  call; nothing runs it on document/data change. A trigger is a later ticket.

**Data completeness (this branch)**
- **Parsed-but-dropped MISMO fields** — borrower `current_address_*` and property
  `county` are parsed but not persisted on this branch (the store-everything work lives
  only on `phase3_5_1`), so they're absent from the `mismo` section. Also no
  account-number column on Stated assets/liabilities → no MISMO account facts (and thus
  no MISMO↔document *account* match-hash; only SSN cross-matches today).
- **No `transaction.*` facts** — bank-statement transactions live inside extraction
  JSON, not as typed MISMO; not surfaced as MISMO facts.

**Extraction / confidence**
- **Per-field extraction confidence is plumbed but sparsely emitted** — the shape and
  storage exist (LP-201), and extractor prompts request it, but coverage/quality is a
  follow-up; a field with no model-reported confidence is honestly `null`.

**Calculations**
- **Cash-to-close is not built** (deferred, net-new — not a snapshot field).
- **Disagreeing-inputs transparency** — a calculation surfaces *its* inputs + source
  tags, but does not reconcile stated-vs-extracted disagreement (that's a downstream
  finding). Which input a calc used is visible via the source tag; a richer
  "both values, here's the one used" view is deferred.
- **Calculators transitively recompute each other** (LTV ×5, MI ×3, DTI ×2 per
  snapshot) — a calculator-layer efficiency coupling, fixed by threading precomputed
  inputs, not in the assembler.

**Matching**
- **Compound/hyphenated surnames** anchor only on the last token (LP-202
  simplification); the nickname map is modest/high-precision, not exhaustive.
- **`belongs_to=None` is lossy-by-design** — it does not distinguish no-match /
  never-attempted / matched-then-removed. Decided (ADR-243/245): keep `None`;
  `fields.asserted_name` gives the only distinction a consumer needs today. Revisit only
  if a rule requires the finer reasons.

**Persistence**
- **No dedup / diffing** across a file's runs — a full blob per run, by decision;
  revisit only if storage hurts.
- **JSONB, snake_case, code-level immutability** are deliberate (ADR-246): no DB-level
  append-only trigger; JSON casing stays snake_case to match the whole app (camelCase,
  if ever wanted, belongs at an API boundary, not in the stored blob).

**Docs/tooling**
- The `_scalar`/`_slug`/`_money` helpers are duplicated across the two assemblers
  (cleanup follow-up). A shared `_AbsentableSection` base for the 4× absent/present/
  missing/failed section pattern is deferred.

## How to build + view a snapshot for a loan file

```bash
cd backend

# 1. (once, if needed) populate document→borrower links via the LP-202 matcher, then
#    build the real snapshot and write the masked JSON artifact:
uv run python -m app.scripts.stage1_artifact LF-6T3N
#    → writes docs/tickets/LP-210-LF-6T3N-snapshot.json (PII masked)

# 2. In code — build, persist, and read back a run's snapshot:
#    from app.verification.snapshot.builder import build_snapshot
#    from app.verification.snapshot.persistence import persist_snapshot, load_snapshot
#    snap = await build_snapshot(db, loan_file_id=..., run_id=..., company_id=...)
#    await persist_snapshot(db, snap)          # immutable, one row per run
#    same = await load_snapshot(db, run_id)    # == snap, PII masked at rest
```

Section-level smokes (each reads real data; need this branch's schema on the DB):
`mismo_section_smoke`, `documents_section_smoke`, `calculations_section_smoke`,
`snapshot_smoke`, `snapshot_persist_smoke` under `app/scripts/`.
