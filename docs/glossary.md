# Glossary

Mortgage processing is a jargon-heavy domain. This glossary defines the domain
and technical terms used throughout mortgageboss-ai. Domain definitions aim to be
accurate and practical; where a term is nuanced or used loosely in the industry,
it is marked **(verify with domain expert)** so the resident expert can confirm.

---

## Domain Terms (mortgage processing)

### Roles and businesses

- **Loan Processor** — the user of this product. Prepares and organizes a loan
  file (documents, data, conditions) so it is complete and accurate before it
  goes to underwriting. Acts as the bridge between the loan officer and the
  underwriter.
- **Loan Officer (LO)** — originates the loan: takes the borrower's application,
  quotes terms, and hands the file off to the processor. Sales-facing.
- **Underwriter (UW)** — the decision-maker at the lender. Reviews the file
  against guidelines and issues the credit decision, usually as an approval with
  **conditions**.
- **Processing Company** — the business that employs processors and is the
  paying customer for this product. May process loans for many loan officers and
  send to many lenders.
- **Lender** — the institution that actually funds the loan (e.g. UWM,
  Sun-West). Sets its own submission requirements and **overlays**.

### Loan lifecycle

- **Origination** — the start of the loan process: application intake by the
  loan officer.
- **Submission** — sending the assembled file to the lender/underwriter.
- **Conditions** — see below; issued by underwriting after review.
- **Clear to Close (CTC)** — all conditions are satisfied and the loan is ready
  to fund and close.

### Loan programs

- **Conventional** — loans that follow Fannie Mae / Freddie Mac guidelines (not
  government-insured). The primary V1 program alongside FHA.
- **FHA** — government-insured loans following HUD guidelines (Handbook 4000.1).
  More lenient credit/down-payment rules; requires mortgage insurance.
- **Conforming** — a loan within the Fannie/Freddie maximum size (the
  "conforming loan limit"). Conventional loans are usually conforming.
- **Jumbo** — a loan that exceeds the conforming limit; underwritten to
  investor-specific rules. **Deferred to V2.**

### Documents and data

- **MISMO** — Mortgage Industry Standards Maintenance Organization; the industry
  XML standard for exchanging mortgage data between systems.
- **MISMO 3.4** — the MISMO version used here, in the "DU wrapper" format
  produced by Fannie Mae's Desktop Underwriter. The structured starting point for
  a loan file's **stated** data.
- **1003 / URLA** — the Uniform Residential Loan Application; the standard loan
  application form. (URLA = the current form; "1003" is its legacy Fannie form
  number.)
- **Stated data** — information as claimed by the borrower / application (sourced
  from MISMO / the 1003). Not yet evidence-backed.
- **Verified data** — information backed by evidence extracted from uploaded
  documents (pay stubs, bank statements, etc.).
- **LOS** — Loan Origination System; the system of record loan officers work in
  (e.g. Encompass, Calyx, Byte).
- **LOE** — Letter of Explanation; a borrower-written note explaining something
  in the file (a credit inquiry, a large deposit, an address gap, etc.).
- **VOE** — Verification of Employment; confirmation of a borrower's employment,
  written (a form) or verbal.

### Calculations

- **DTI — Debt-to-Income ratio** — a borrower's monthly debt obligations as a
  percentage of gross monthly income. A primary qualifying metric.
- **Front-end DTI** — the housing payment (PITI) divided by gross monthly income.
- **Back-end DTI** — total monthly debts (housing + all other obligations)
  divided by gross monthly income.
- **LTV — Loan-to-Value ratio** — the loan amount divided by the property value
  (lower is less risky).
- **CLTV — Combined Loan-to-Value** — all loans secured by the property (e.g. a
  first plus a second/HELOC) divided by the property value.
- **PITI** — Principal, Interest, Taxes, and Insurance: the full monthly housing
  payment. (Sometimes "PITIA" when HOA dues are included — **verify with domain
  expert** for how this product should treat HOA.)
- **MI / PMI / MIP** — Mortgage Insurance generally; **PMI** is Private Mortgage
  Insurance on conventional loans (typically required when LTV > 80%); **MIP** is
  the FHA Mortgage Insurance Premium.

### Conditions

- **Condition** — an item the underwriter requires before the loan can proceed.
  The file's to-do list coming out of underwriting.
- **PTD — Prior to Docs** — a condition that must be satisfied before closing
  documents are drawn.
- **PTF — Prior to Funding** — a condition that must be satisfied before the loan
  is funded (later than PTD).
- **Routine condition** — an expected timing/sequencing item (e.g. "provide
  updated pay stub within 10 days of closing") — not a sign of a problem.
- **Should-have-caught condition** — an issue the processor could and should have
  caught before submission. Reducing these is a core value proposition of this
  product. **(verify with domain expert — exact framing.)**
- **UW Round** — one cycle of underwriting review (submit → conditions →
  resubmit). Fewer rounds = faster, cheaper closings.

### Rules and verification

- **Investor guidelines** — the baseline rulebooks: the Fannie Mae Selling Guide
  (conventional) and HUD Handbook 4000.1 (FHA).
- **Lender overlay** — a rule a specific lender layers *on top of* investor
  guidelines that is **stricter** than the baseline (e.g. a higher minimum credit
  score).
- **Regulatory rules** — universal rules from federal regulation that apply
  regardless of lender or program (e.g. TRID disclosure timing).
- **Cross-source consistency** — checking that the same fact agrees across
  sources, especially **stated** vs **verified** data (e.g. stated income on the
  1003 vs income computed from pay stubs).
- **TRID** — "TILA-RESPA Integrated Disclosure"; the federal rule governing loan
  disclosure forms and timing. **(verify with domain expert for V1 scope.)**

---

## Technical Terms (architecture / tooling)

- **ADR — Architecture Decision Record** — a short, dated note capturing a
  technical decision and its rationale. Logged in
  [`../decisions.md`](../decisions.md).
- **CI/CD — Continuous Integration / Continuous Deployment** — automated checks
  (and, later, deployments) run on every change. See
  [`development-workflow.md`](development-workflow.md).
- **ORM — Object-Relational Mapping** — mapping database rows to Python objects;
  here, SQLAlchemy 2.x in the typed `Mapped[...]` style.
- **JWT — JSON Web Token** — a signed token used for authentication (access +
  refresh tokens). Arrives in Epic 3.
- **CORS — Cross-Origin Resource Sharing** — browser rules controlling which
  origins may call the API; configured from settings on the backend.
- **Async / await** — Python's asynchronous programming model. This project is
  async-first: async route handlers, async database sessions, async AI calls.
- **Celery** — a distributed task queue (with a Redis broker) used to run the
  document classification/extraction pipeline outside the request cycle.
- **Migration** — a versioned, replayable change to the database schema, managed
  by Alembic. Arrives in Epic 2 (LP-9).
- **Soft delete** — marking a record deleted (a `deleted_at` timestamp) instead
  of physically removing it, preserving history and the audit trail.
- **Versioning** — keeping prior versions of derived data (e.g. document
  extractions, verification runs) rather than overwriting, so changes are
  auditable and re-runnable.
- **Multi-tenancy** — isolating each processing company's data within a shared
  database, scoping every query by `company_id` so one tenant can never see
  another's data.
- **Audit log / activity log** — an append-only record of who (user, system, or
  AI) did what and when, for traceability.
- **MailHog** — a local SMTP server that captures outgoing email for inspection
  in development (web UI at `localhost:8025`); no mail leaves the machine.
