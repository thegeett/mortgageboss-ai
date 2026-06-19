LP-51 — MISMO Parsing Core (prompt already written)
The deterministic foundation: XML/HTML → structured data.

Deterministic lxml/XPath parser (no AI); tolerant of optional/missing elements; reads values exactly (Decimals/dates/SSN)
Typed core (borrower, loan, property, income, employers, declarations, liabilities, assets) + catch-all (everything else) — nothing dropped
Accept raw XML and HTML-wrapped XML (extract embedded XML first)
Validation + graceful errors (not-XML / not-MISMO / missing-required → clear errors, never crash)
Tested against the real MISMO16940192.xml fixture with exact-value assertions; SSN/PII never logged
Output: parse_mismo(content) → ParsedMismo (structured intermediate representation)


LP-52 — Stated-Financials Data Model + Migrations
The new DB structures for the "stated" side (shaped for Phase 3 cross-checks).

New models for stated financial data the existing schema doesn't hold: stated income items, stated assets, stated liabilities, stated employers (each structured/typed for deterministic comparison in Phase 3)
A catch-all storage field for the full MISMO data (the rest of the typed-core+catch-all, kept for later) + storage of the original raw MISMO file (audit)
Confirm/extend Borrower/Property/LoanFile to hold the MISMO-sourced core fields (DOB, marital status, citizenship, declarations; property value/usage; loan terms) — add fields where Epic 4's manual-creation schema is missing them
Tenant-scoped via loan_file (ADR-053); SSN through the encrypted path; Alembic migrations
Note: the exact stated-financials shape is shaped by Phase 3 verification — a starter set now, refined as Phase 3 rules firm up (and with Priya)


LP-53 — MISMO → Models Mapping + File Creation Service
The service that turns ParsedMismo into a populated loan file.

A mapping layer: ParsedMismo (LP-51) → LoanFile + Borrower(s) + Property + stated-financials models (LP-52) + the catch-all
Creates the loan file directly (import-directly decision — no preview/confirm), populated from the parsed data, tenant-scoped
Stores the raw MISMO file (audit) and the catch-all (everything-else, available later)
SSN encrypted on store; masked in any output
Graceful handling: a partial parse (missing fields + warnings from LP-51) still creates the file with what's present, surfacing warnings
Output: create_loan_file_from_mismo(parsed) → LoanFile — converges on the same LoanFile that manual creation produces


LP-54 — MISMO Upload Endpoint + Processing
The API entry point: upload → parse → create.

POST endpoint accepting a MISMO XML or HTML-wrapped file upload (multipart; size/type validation; the HTML/XML sniff from LP-51)
Pipeline: receive file → parse_mismo (LP-51) → create_loan_file_from_mismo (LP-53) → return the created file
Tenant-scoped (company from the authenticated user); the created file belongs to the user's company
Graceful errors surfaced via the LP-46 error envelope (malformed/not-MISMO/parse-failure → clear messages, no crash)
Tested end-to-end (real fixture → file created with correct stated data); integration + tenant-isolation tests
Note: decide whether parsing runs inline (fast — MISMO is small, ~60KB) or on the Celery queue. Likely inline (it's fast deterministic parsing, no AI, unlike document processing) — but flagged as a decision


LP-55 — MISMO Upload Frontend (Primary Create-File Path)
The UI: "Upload MISMO" as the primary path, alongside manual creation.

Updated "New File" flow with two entry points: "Upload MISMO" (primary, drag-and-drop XML/HTML) and "Create manually" (the Epic 4 fallback)
On upload → calls LP-54 → the populated loan file opens (import-directly); loading/error states (LP-46/47)
Display the imported stated data on the file (borrower, property, loan, stated income/assets/liabilities) — and surface any parse warnings
Frontend-design skill; consistent with the existing file-creation/detail UI
Output: the processor uploads the LO's MISMO handoff → a populated file appears


LP-56 — Edit Imported Data (Reviewable/Editable After Import)
The "import-directly but editable afterward" half of the decision.

The imported stated data (borrower, property, loan, stated financials) is reviewable and editable on the file after import — so a parsing gap on a variant file can be corrected, not permanent
Edit endpoints + UI for the MISMO-sourced fields (reusing/extending Epic 4's edit paths where they exist)
Edits are audited (activity log); tenant-scoped
Why separate: the import-directly decision explicitly requires post-import editability; this is the safety net for parser gaps. Could fold into LP-55 if you prefer fewer tickets


LP-57 — Phase 1.5 Testing, Polish & Multi-File Hardening
Consolidation (mirrors Phase 1's Epic 6 pattern).

Integration tests for the full MISMO flow (upload → parse → create → display → edit); tenant isolation
Harden tolerance against more real files — re-supply 1–2 additional real MISMO exports (different borrower/LOS) and confirm the parser handles their variation (this is where parser robustness is really proven)
Polish (loading/error/empty states for the MISMO flow); seed-data update (LP-48) to include a MISMO-imported file
Phase 1.5 docs/review; the deferred items (re-import/versioning/diff, smart-needs-from-MISMO) noted as future
Note: the original plan's "smart needs list from MISMO" (self-employed → tax returns, multiple properties → leases, etc.) is a meaningful sub-feature — I've left it as a future/Phase-2-adjacent item here rather than a V1.5 ticket, because it needs Priya's input on the rules. Flag if you want it pulled into Phase 1.5 as its own ticket (it'd be LP-58)
