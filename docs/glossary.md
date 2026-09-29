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
  From Phase 4.5 this means the lender's own **verbatim demand** on a condition
  sheet (ADR-403) — not our checklist. The document we chase in order to satisfy
  one is a **need**: a separate record, in our words, that we may rewrite and
  close. A condition is closed only by the lender.
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

Phase 4.5 works with the lender's own condition documents, which needs a few more
terms (LP-903):

- **Condition sheet** — the document the lender issues listing its conditions.
  UWM calls it a "Loan Approval Conditions" letter; Champions Funding calls it a
  "Conditional Approval Certificate". One sheet is one **round**.
- **Round** — one condition sheet received for a file, and the unit this product
  stores. Round 1 is the first approval; later rounds are re-issues after the
  processor submits documents. This is the record of a **UW Round** above: the
  cycle is the event, the round is the sheet it produced. A round records how it
  arrived (**source**) and whether it is the lender's whole list
  (**completeness**).
- **Lender code** — the lender's own template ID for a condition, printed on the
  sheet (UWM `7086` = short funds to close). **Meaningful only per lender** — the
  same demand is `268` at Champions — so codes are always stored and matched as
  (lender, code), with leading zeros kept (ADR-407).
- **Bucket** — the heading a condition is listed under, which says *when* it must
  be satisfied: Master, Prior to Docs (**PTD**), Prior to Funding (**PTF**),
  lender-internal ("Underwriter To Obtain And Clear"), or trailing. The heading is
  stored exactly as the lender printed it; the *kind* follows its parenthetical.
- **Underwriter note** — a dated note the underwriter appends inside a condition's
  text, e.g. `**8/28 Not in Upload`. It means the condition came back. The note
  stays part of the lender's wording and is also extracted with its date; it is
  excluded from the text fingerprint, so a condition that comes back is still
  recognised as the same condition.
- **Source** — how a round arrived: the lender's PDF, a forwarded email, text
  pasted from the portal, or typed by hand. Shown on every round, because what a
  round can be trusted to prove depends on it.
- **Completeness** — whether a round is the lender's **full list** or **just
  some** of it. Only a full list can support "this one is gone, so it probably
  cleared"; a partial source may add and update, never remove or clear (ADR-404).

Stage 2 makes the two statuses move, which needs the words for them (ADR-408):

- **Our status / preparation track** — what *we* are doing about a condition: To
  do, Waiting on someone, Ready to send, Sent to lender. It says nothing about
  whether the lender has accepted anything. Moving *forward* needs no reason;
  moving *back* needs one, because backwards is something having gone wrong and
  the reason is the only record of what.
- **The lender's status** — what the *lender* said: Open, Came back, Cleared,
  Waived, Replaced. A condition can be fully prepared and submitted and still be
  Open, which is why the two are tracked separately.
- **Verdict** — the record of *who said so and where*: the answer (cleared,
  waived, came back), where it was said (portal, email, phone, a round
  comparison, an underwriter's note), **the date the lender said it** — never
  today by default — and who recorded it. **Nothing may say a condition is
  Cleared or Waived without one** (ADR-404, ADR-408). It is what makes "cleared
  on the 12th" checkable months later: it says where to look.
- **Came back** — the lender has answered and the answer is no, so the work is
  back with the processor. Usually set by the lender's own new dated
  **underwriter note**, which is the lender reopening the condition in its own
  words.
- **Waived** — the lender dropped the condition. Cleared and waived are different
  facts and both need a verdict: one says the demand was met, the other that it
  no longer applies.
- **Replaced (superseded)** — the lender reworded a condition and the processor
  confirmed the two are the same demand. The old one stays, struck through,
  pointing at the one that carries on from it. Nothing disappears.
- **Probably cleared** — a *suggestion*, never a status: a condition that was open
  and is absent from a new **full list**. It is always a question with a button,
  and confirming it is what records the verdict (ADR-404).

Stage 3 turns a condition into work: what it asks for, who does it, and what
arrives (ADR-409 to ADR-416):

- **Condition library / condition type** — our reviewed list of the kinds of
  condition lenders issue (55 types, ids like `AS-10` "Short funds to close or
  reserves"). A lender code is mapped to a type once per lender; the type says
  what items the condition breaks into, who usually acts, what the evidence is
  checked for, and the sentence the email uses. It is data in the repository, not
  model output (ADR-409).
- **Reading** — what a condition asks for, in our terms: its items, who acts on
  each, and the specifics (amounts, the account's last four, months). Made by one
  AI call per round, or by the library alone when the AI is off; a reading below
  the confidence bar, or from the library alone, waits for the processor to
  confirm it. Every figure in a reading must be in the lender's own text
  (ADR-410).
- **Item** — one thing a condition needs, with who does it: 6637's earnest money
  is three items (the source → borrower, the receipt → title, the clearance →
  borrower). One document may answer items on several conditions.
- **Plan / next step** — for each item (or the whole condition), how it will be
  done: **Ask the borrower** (or another party), **I'll do it** (the processor's
  own task), **Already in the file**, **Push back** (a question to the
  underwriter), **Lender is doing it**, or **Information only**. The plan is a
  proposal until she confirms it; after that, a step that needs nothing more
  moves the condition to Ready to send, forward only (ADR-411).
- **Condition draft** — an email the app writes for a round (one per recipient:
  borrower, title/attorney, LO, a question to the underwriter). **Nothing is sent
  by the app**: she copies it into her own mail, sends it, and marks it sent,
  which moves the asked conditions to Waiting on that person (ADR-412). **Polish
  with AI** proposes a better-worded version; a changed or dropped fact is shown
  with a warning, and her click applies it (ADR-413).
- **Evidence check** — what code checks on a document that arrives for an item:
  right account, right period, right borrower, inside the lender's dates, all
  pages, the amount, and whether the funds cover what is required. A statement
  that fails one of its own checks (other than the funds total) is **rejected**:
  it is not evidence, its balance counts for nothing, and she may **accept it
  anyway** with a reason that is kept (ADR-414).
- **Large deposit** — a deposit over 50% of the monthly income used to qualify
  (Fannie Mae B3-4.2-02; $2,870.66 on $5,741.32). If the funds to close need it,
  it must be **sourced**: she asks the borrower for a letter, or records how it is
  already explained. Payroll deposits are not large deposits.
- **Figures check** — what accepted evidence changes in the file's figures
  (verified assets, the insurance premium, the ratios), computed by code and
  shown as a proposal. Nothing changes until she applies it (ADR-415).
- **DU re-run** — whether the loan must be resubmitted to Desktop Underwriter
  after the figures change: Fannie Mae B3-2-10's tolerances. The recalculated
  DTI crossing 45% (44% → 46% yes, 46% → 48% no); rising 3 points or more while
  it is 50% or less (35% → 40%, 46% → 50%); any recalculated DTI over 50%; or
  income or reserves falling short. Confirmed by the product owner, 2026-09-29
  (LP-936).
- **Condition package** — what goes to the lender for a round: one PDF per Ready
  condition, named with the lender's code (`7086 - Assets.pdf`), and one note per
  condition for the underwriter. She downloads it and uploads it herself, in the
  lender's portal (UWM's is **EASE**), then presses **Mark submitted**, which
  moves exactly those conditions to Sent to lender. The lender's status never
  moves by it (ADR-416).
- **Upload cutoff** — the time of day by which a lender wants condition uploads
  (UWM: 8:00 PM Eastern). Set per lender and counted down on the package. What
  happens to an upload after it is the lender's rule, not the app's **(verify
  with domain expert)**.
- **Mortgagee clause** — the lender's name and address as it must appear on the
  homeowners insurance policy (UWM's begins "United Wholesale Mortgage ISAOA,
  ATIMA"). Set per lender, filled from the approval letter until saved. The plan
  requires the clause on the declarations page (Fannie Mae B7-3-07 / B7-3-08) and
  the insurance email carries it verbatim from the letter. What the clause does,
  and what ISAOA and ATIMA stand for, is not stated anywhere in this repository:
  the app copies the letter's words and never composes them **(verify with domain
  expert)**.
- **Lender codes to review** — lender codes seen on sheets that no library type
  covers yet. An admin chooses the type once, and later imports use it.

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
