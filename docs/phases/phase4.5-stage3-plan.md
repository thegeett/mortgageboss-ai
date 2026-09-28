# Phase 4.5 Stage 3 ("Work the conditions"): plan

**Status:** draft v2, reviewed against the code and the research · 2026-09-28
**Screens:** `docs/design/phase4.5-conditions/stage3/` (12 reference screens, S3-01 to S3-12)
**Builds on:** Stage 1 (get conditions in) and Stage 2 (see and track them), both built on
`phase4.5-conditions`.
**Replaces:** §5 of `docs/phases/phase4.5-build-plan.md` (v3), which is updated by what we learned in
Stages 1–2 and in new research.

---

## 1. What Stage 3 delivers, in one screen

Today, after Stage 2, the app knows **what** the lender asked and **where each condition stands**. The
processor still does all the work by hand: she reads each condition, works out who has to act, writes
the emails, chases the documents, checks them, and builds the upload.

**After Stage 3, when a condition sheet arrives, the app does the preparation and she makes the
decisions:**

1. **It reads each condition** and splits it into the separate things being asked for, with who has
   to act on each one. For example, 6637 (earnest money) becomes three items: the source (borrower),
   the receipt (title/escrow), and the clearance (borrower's bank statement).
2. **It proposes a plan for every condition:** ask the borrower, ask a third party, "I'll do it",
   "already in the file", ask the underwriter, push back, or "the lender is doing it".
3. **It drafts the emails.** One email to the borrower covering everything they owe, one per third
   party (title, insurance agent, HOA, employer, LO), and a question to the underwriter when a
   condition is unclear or doesn't apply. **Nothing is sent by itself.** She reviews, clicks
   "Copy & open Gmail", sends, and clicks "Mark as sent", exactly as with today's document requests.
4. **It watches for the answers.** When a document comes back, by email to the file's inbox or by
   upload, it links the document to the right item and **checks it the way an underwriter would**:
   all pages, the right account, dated inside the lender's expiry dates, and no new problems such as
   a new large deposit.
5. **It watches the numbers.** When a condition changes a figure (verified assets, income, the
   insurance premium), it works out the effect on DTI and reserves **by code**, and says so when the
   change means the loan must go back through DU.
6. **It builds the upload package.** One file per condition, named by its code, with a one-line note
   per condition explaining how the evidence answers it, and a warning if anything prior-to-docs is
   still open.

Her statuses move on their own as this happens. *Waiting on Borrower* is set when the email is marked
sent, and *Ready to send* when the evidence passes its checks. The lender's status still changes only
when **she records what the lender said**, as in Stage 2.

### The outcome, measured

| Today (by hand) | After Stage 3 | How we will measure it in the pilot |
|---|---|---|
| Reading a sheet and working out who does what: 30–60 min per round | Minutes: she confirms the app's plan | Time from import to "all asks sent" |
| Borrowers asked more than once | One consolidated borrower email per round; nothing asked twice | Duplicate asks per file (target 0) |
| Documents checked at upload time, or not at all | Checked the moment they arrive | Conditions that come back "not in upload" or "not sufficient" |
| Package assembled by hand before the cutoff | Built by the app, reviewed by her | Time from "all ready" to "submitted" |
| Surprise re-runs of DU found by the lender | Flagged by the app before submission | DU re-run findings raised by the lender |

**Stage 3 exit test** (the same synthetic copy of the test file as Stages 1–2): she goes from round 1
to "all prior-to-docs items submitted" inside the app. Every ask is drafted for her, every returned
document is checked, and nothing is marked cleared that the lender didn't clear.

---

## 2. What the research says

### 2.1 What a processor actually does with a condition

Our September research (`phase4.5-condition-research.md`, §1.1 and §4) found that asking the borrower
is the biggest bucket of work, but only one of about eleven kinds of action. Stage 3 has to cover them
all, at least as a choice she can make:

| Kind of action | Example on real sheets | What Stage 3 does |
|---|---|---|
| Ask the borrower | 6132 another bank statement, 7086 more assets | Adds it to the one borrower email |
| Order from a vendor | Credit supplement, VOE through The Work Number | Records it as her own task, with the result to attach |
| Ask a non-vendor third party | 6178 insurance dec page, 1947 seller CD from title, HOA questionnaire, payoff | One email per party |
| Verify and certify herself | Verbal VOE, processor certification | "I'll do it" task with a log (who, when, phone source) |
| Write something | The note per condition; an explanation letter for the borrower to sign | Drafted by the app, edited by her |
| Fix data / re-run DU | 7086 when verified assets change | The figures check (LP-924) flags it |
| Disclosures | Change of circumstance (0571), revised CD | Flags that the LO or lender must act; no disclosure work in the app |
| Push back / ask the underwriter | 6178 doesn't apply if closing is on or after 09/30 | Drafted question or push-back, with the reason |
| Coordinate | 0007 invoice waits on 1228 final inspection | Links between conditions |
| Check before upload | All pages, dates, names | Evidence checks (LP-923) |
| The lender does it | 1760 desk review, 0571 CoC approval | Watch only, no ask |

The routine experienced processors follow (NAMP, Scotsman Guide, STRATMOR): read everything first,
sort by *when* and *who*, clear your own items the same day, send the borrower **one** consolidated
request, order third-party items in parallel, check each document when it arrives, and submit one
complete package before the lender's cutoff (UWM: 8 p.m. ET).

### 2.2 Asking the borrower once matters a lot

A STRATMOR/Snapdocs survey of more than 7,000 recent borrowers found that **36% had to provide
documents more than once, and that cost lenders 11 points of Net Promoter Score**. Providing documents
was the lowest-rated part of the whole mortgage process (7.87 of 10). This is the single strongest
argument for Stage 3's "one borrower email per round, including items we already know will be
needed" rule.

### 2.3 The rules the app has to get right

These become code checks, not AI judgements:

| Rule | Source | Where it is used |
|---|---|---|
| A **large deposit** is a single deposit over **50% of total monthly qualifying income**; it must be sourced on purchases when the funds are needed. Deposits the statement itself explains (payroll, SSA, IRS refund) need nothing more. | Fannie Mae B3-4.2-02 | Evidence checks: a new statement is scanned for deposits over the threshold |
| **Earnest money:** receipt verified by a copy of the canceled check or a written statement from the holder of the deposit; if it is part of the minimum contribution, its source must be verified, with statements covering up to the date the check cleared | Fannie Mae B3-4.3-09 | Splits 6637 into its three items and checks each |
| **DU resubmission** is required if the recalculated DTI **exceeds 45%, or rises by 3 points or more**; if verified income is lower than the application; if reserves fall below what DU required (unless at least 90% of it) | Fannie Mae B3-2-10 | Figures check: "this change means DU must be re-run" |
| **Verbal VOE** within 10 business days before the note date (self-employed: 120 calendar days) | Fannie Mae B3-3.1-04 (verified in September's research) | "I'll do it" task with the date it must be redone by |
| **Payoff statements**: the servicer must respond within 7 business days | Reg Z 1026.36(c)(3) | Third-party ask with an expected date |
| **Insurance:** the dec page must show the wholesale lender's mortgagee clause (ISAOA/ATIMA) | Fannie Mae B7-3-07 / B7-3-08 | The insurance email includes the clause from the letter (Stage 1 already reads it) |
| **Customer information must be encrypted in transit over external networks and at rest** (or protected by approved compensating controls) | FTC Safeguards Rule, 16 CFR 314.4(c)(3) | Emails never carry full account numbers or SSNs; documents come back through the file's inbox or upload, not as replies scattered across mailboxes |

### 2.4 Where the market is going (and what it means for us)

- **Lenders are taking processing in-house.** On **23 September 2026** UWM launched *Underwriting+*:
  one UWM underwriter gathers documents, talks to the borrower and third parties, and clears
  conditions. The pilot averaged 8.3 days from submission to clear-to-close and 2.1 underwriting
  touches per file, and brokers get three loans free through 31 December 2026. UWM also runs
  *Processor Assist*, which orders title, insurance, payoffs and condo documents itself.
  **For us:** some conditions will increasingly be done *by the lender*. Stage 3 must treat "the
  lender is doing it" as a first-class performer, with watch-and-chase rather than ask. The value we
  add is strongest on the lenders and files where the processing company still does the work, and in
  the checks and packaging a lender-side process doesn't do for the broker.
- **"Condition elimination" over "condition management".** An MBA NewsLink piece (May 2026) argues the
  goal is to anticipate routine conditions (document expiry, flood, data gaps) rather than manage them
  after the fact. This supports Stage 4's clocks and "preventable conditions" work, and Stage 3's rule
  of asking early for items we already know will be needed.
- **AI agents in this space keep people on the judgement calls.** Vendors building AI for
  large-deposit sourcing compute the threshold per loan, clear what the statement explains, and route
  anything that looks like suspicious activity to people. They never decide it. Stage 3 follows the
  same line: AI reads and drafts, code decides numbers and dates, and she decides.

---

## 3. What we already have to build on

Stage 3 is mostly **wiring existing pieces to conditions**, not new machinery:

| Existing piece | What it does today | What Stage 3 uses it for |
|---|---|---|
| Needs engine (LP-68) with `NeedsItemOrigin.CONDITION` reserved | Needs with Pending → Requested → Received → Verified / Rejected / Waived | Every document item a condition asks for becomes a need |
| Needs dedup (LP-111) and coverage (LP-631) | Merges duplicate needs; flags a need the file already answers | "Already in the file" and "never ask twice" |
| Accumulating email draft (LP-809) and draft-only sending (LP-849–858) | One borrower email holding a set of needs; Copy & open Gmail; Mark as sent | The one borrower email per round |
| Party requests (LP-820) | One draft per third party (title, insurance…), with a missing address asked once | Title, insurance agent, HOA, employer, LO emails |
| Lender contacts (LP-813) | The underwriter and lender team on a file | Questions and push-backs to the right underwriter |
| Reminders (LP-814) | Suggests follow-ups from the date something was requested; never sends | Chasing |
| Inbound mail and document classification/extraction | Documents arrive by email or upload and are read | Evidence arriving for a condition |
| Verification engine and findings (Phase 3) | Checks documents against the file; raises findings | New problems in returned evidence (for example a new large deposit) |
| Borrower upload links (`services/upload_links.py`) | A secure link a borrower uses to upload documents | Where evidence comes back, instead of email attachments |
| Stated financials, editable (`api/stated_financials.py` PATCH on assets, income, liabilities, employers) | The file's own figures, corrected by hand | The figures check (LP-924) proposes a change; applying it uses these endpoints |
| AS-1 large-deposit rule (threshold "50%" stored as data in `verification/rules/specs.py`) and the DTI calculator (`verification/dti.py`) | Existing verification rules and ratios | Evidence checks and the figures check reuse them, so there is no second copy of either rule |
| Lender package tab | **A placeholder** ("Phase 6") | Not used. The condition package lives on the Conditions tab (LP-925), so Phase 6's full package is not pre-empted |
| Stage 2 statuses, verdicts and events | Two tracks; every change is an event | Status moves driven by actions, all kept in history |

---

## 4. Principles for Stage 3

1. **AI reads and drafts. Code decides numbers and dates. The processor decides.**
2. **Nothing is sent by itself.** Every message is a draft until she sends it and marks it sent.
3. **Only the lender clears.** Stage 3 can move *our* status on its own (Waiting, Ready, Sent); only a
   recorded lender answer changes the lender's status.
4. **Ask each person once per round.** Borrower items are gathered into one email, including items we
   already know will be needed later.
5. **The library beats the AI.** A known (lender, code) or a known condition type decides the plan;
   AI fills in specifics and handles the unknown. Low confidence asks her to confirm.
6. **The lender's words are always visible** beside the app's reading of them.
7. **The loan snapshot never goes to AI.** The AI sees the condition text and a short file summary
   (borrowers, accounts by bank and last four, employers, earnest money, closing date, parties).
8. **Every action and every automatic move is an event.** She can always see why something happened.
9. **The lender can be the performer.** "The lender is doing it" is a real plan, not a gap.

---

## 4a. What the review changed (v2)

I reviewed v1 against the code on `phase4.5-conditions` and the research once more. These are the
changes:

1. **Split into two releases, so value arrives earlier.**
   - **Stage 3A: read, plan and ask** (LP-918 to LP-922). After 3A a sheet arrives, the plan is ready,
     and the emails are drafted. This is most of the time saved.
   - **Stage 3B: check, figures and package** (LP-923 to LP-925). Each has its own acceptance test.
2. **One document can answer several conditions.** One bank statement can answer 7086 (assets),
   6132 (the next month) and 6637 (the earnest money cleared). Items point at **needs**, and a need can
   serve items on several conditions. The borrower is asked for that statement once, and it is
   checked once for each item it answers.
3. **Plans carry over between rounds.**
   - A condition seen again keeps its plan and progress.
   - A condition that came back reopens the items the note is about, and the note is shown with the
     re-ask.
   - A replaced (reworded) condition hands its plan to the new one, and she confirms.
4. **The lender package tab is a placeholder** (planned for Phase 6), not a feature to reuse. The
   condition package is built on the Conditions tab.
5. **Applying a figure change uses the existing stated-financials edits.** The figures check proposes
   and she confirms; nothing new writes loan figures.
6. **Evidence comes back through the existing borrower upload link.** The link is scoped to this
   round's items, so the borrower sees exactly what is asked. Email to the file's inbox still works.
7. **Sun West asks for more on each upload:** a comment per condition, plus "Name of Source" and "Date
   Verified" (September research §3.2). The package carries these per condition, alongside UWM's
   note.
8. **"Lender is processing this file" is a file-level switch** (for example a UWM Underwriting+
   file). When it is on, third-party items default to *lender is doing it* instead of *ask*.
9. **If the AI is unavailable or unsure, the plan still works.** The library's default plan is used,
   and the reading is marked for her to confirm. Nothing waits on AI (build plan principle 4).
10. **Automatic status moves are listed and each writes an event:**
    - an email marked sent moves its conditions to *Waiting on …*;
    - evidence passing every item moves a condition to *Ready to send*;
    - a package marked submitted moves its conditions to *Sent to lender*;
    - a came-back note moves a condition back to *To do* (Stage 2).

    Nothing moves the lender's track.
11. **Pilot measurements are recorded as events from day one:**
    - the time from import to "all asks sent";
    - asks per item (to catch duplicates);
    - checks that failed on arrival;
    - DU re-runs flagged.

    §1's outcome table can then be measured, not estimated.
12. **No new values for our status.** "Lender is doing it" and "Information only" are **plan
    options**, not new `prep_status` values. The list and the sheet show them with Stage 2's existing
    display rule (today triggered by `bucket_kind`), now also triggered by the chosen plan option.
    Underneath, `prep_status` stays `to_do`, and neither counts in "your tasks" or "waiting on others".
    No CHECK constraint changes for this.
13. **Reference screens are drawn** (S3-01 to S3-12, §7). Each UI ticket lists the screens it builds
    to and records a visual check, as in Stages 1 and 2.

## 5. The tickets

Eight tickets, about the same size as Stage 1. The order matters: the library and the reading come
first, because every later ticket consumes their output.

### LP-918 · The condition library v1 (data, with you) · M

**What it is:** a reviewed list of about **40 condition types** covering the ones on your real sheets
and the common agency conditions (taxonomy IDs such as AS-01 bank statements, AS-04 earnest money,
AS-10 short funds, IN-01 insurance dec page, IE-03 verbal VOE). Each type records:
- the **items** it usually asks for, and **who provides each** (borrower, title, insurance, HOA,
  employer, LO, processor, lender);
- the **documents that satisfy it**, mapped to the app's existing document types;
- the **default plan** (ask borrower, ask party, I'll do it, lender does it, information only);
- the **checks** evidence must pass (pages, dates, amounts);
- the **rule behind it** (agency guide section, or "lender overlay");
- a **short playbook line** for the processor.

Every UWM and Champions code from Stage 1's code map gets a type.

**Your part:** review and sign off the **top 20** types. I'll prepare them as a table you can mark up;
it's about two hours of your processor knowledge. This is the one ticket Claude Code cannot finish
alone.

**Done when:** you have signed off the top 20, and every mapped lender code resolves to a type.

**Reference screens:** none of its own. The codes-to-review table it feeds is drawn on
`docs/design/phase4.5-conditions/stage3/screens/S3-11-lender-settings.png` (built in LP-925).

### LP-919 · Reading each condition (AI understanding) · L

**What it is:** one AI call per round (not per condition) that turns each condition into items.

For each condition it returns:
- the **items** asked for (a compound condition becomes several);
- **who acts** on each item;
- the **specifics**: amounts, accounts (bank + last four), dates, names;
- whether it is **information only** or a real request;
- what any **underwriter note** means ("Not in Upload" means the upload was missed);
- a **plain-English one-liner**; and
- a **confidence**.

**Guardrails:**
- A known (lender, code) from the library decides the type; the AI only fills in specifics.
- Every number the AI returns is **re-computed by code** from the lender's text. For example, 7086's
  shortfall is $38,210.40 required − $11,062.18 verified = **$27,148.22**.
- Below the confidence bar, she confirms the reading before anything is drafted.
- The loan snapshot never goes in (principle 7). The AI only structures what the lender wrote.
- Cost is tracked with the existing AI cost tool, and it is **one call per round**.
- **If the AI fails or is unavailable, the library's default plan is used**, and the condition is
  marked "Please confirm how we read this". The round is never stuck.

**Done when**, on the test file's round 1:
- 6637 becomes three items across the borrower and title/escrow;
- 0132 becomes three items across the LO, the borrower and the attorney;
- 7086's shortfall is computed by code;
- on the page-break fixture, 1760 (desk review ordered) and the three 0571 rows (change of
  circumstance) are "the lender is doing it";
- 6178 is flagged "may not apply": the letter itself says *must not close before 09/30/2026*, which is
  the date the insurance policy starts.

**Reference screens (build to these):** read `docs/design/phase4.5-conditions/stage3/README.md` first, then match each PNG and go
through its *Must match* list. The HTML of the same name in `docs/design/phase4.5-conditions/stage3/html/` has the exact wording.
- `docs/design/phase4.5-conditions/stage3/screens/S3-01-condition-items.png` (the reading box and the items on the detail sheet)
- `docs/design/phase4.5-conditions/stage3/screens/S3-03-confirm-reading.png` (a reading below the confidence bar)
Record the result under **"Visual check"** in the ticket file, screen by screen. A
difference that is not on that screen's *May differ* list is fixed, or it is a **STOP AND ASK**.

### LP-920 · The action plan · M

**What it is:** from the items, the app builds a plan she can edit.
- **Items and actions** are saved per condition: the kind of action, the performer (you, borrower, LO,
  lender, third party), the counterparty, the due date, the status and the outcome.
- **Needs from conditions:** every document item becomes a need with `origin = CONDITION`, merged with
  needs the file already has (never two asks for the same document).
- **Already in the file:** when the file already holds a matching document (existing coverage
  check), the plan says "point to it" instead of asking.
- **Links:** one condition can wait on another (0007's inspection invoice waits on 1228's
  inspection).
- **Due dates** are worked back from the lender's dates (must not close before, lock expiry, expiry
  table), all of which Stage 1 already reads.

- **One need can serve several items** (review change 2). The borrower is asked once; each item
  still has its own check.
- **Carry-over between rounds** (review change 3).
- **A file-level switch, "Lender is processing this file"**, changes third-party defaults (review
  change 8).

**Done when:**
- importing round 1 produces the plan below (§6) without her creating anything by hand, and she can
  change any part of it;
- importing round 2 keeps the plan for the six conditions seen again.

**Reference screens (build to these):** read `docs/design/phase4.5-conditions/stage3/README.md` first, then match each PNG and go
through its *Must match* list. The HTML of the same name in `docs/design/phase4.5-conditions/stage3/html/` has the exact wording.
- `docs/design/phase4.5-conditions/stage3/screens/S3-01-condition-items.png` (items, who acts, shared items asked for once)
- `docs/design/phase4.5-conditions/stage3/screens/S3-02-round-plan.png` (the plan for round 1, before confirming)
Record the result under **"Visual check"** in the ticket file, screen by screen. A
difference that is not on that screen's *May differ* list is fixed, or it is a **STOP AND ASK**.

### LP-921 · Next-step options on every condition · M

**What it is:** each condition in the list and the detail sheet shows the options that fit its
items:

| Option | What it does | Our status becomes |
|---|---|---|
| Ask the borrower | Adds the item to this round's borrower email | Waiting on Borrower, once the email is marked sent |
| Ask a third party | Adds it to that party's email (title, insurance, HOA, employer, LO) | Waiting on *party* |
| I'll do it | Creates her own task (upload the invoice, log the verbal VOE call) | stays To do until done, then Ready |
| Already in the file | Links the document and page | Ready |
| Ask the underwriter | Drafts a question to the right person on the lender team | Waiting on Lender |
| Push back | Drafts a short explanation with the reason (for example 6178's date) | Waiting on Lender |
| Lender is doing it | Watch only | Lender is doing it |
| Information only | Nothing to do | Information only |

"Lender is doing it" and "Information only" are shown with Stage 2's display rule and add no new
status values (review change 12). The list gains a **Next step** column and three summary numbers:
Waiting on others, Your tasks, Failed a check (S3-12).

**Done when** every condition on round 1 has at least one sensible option pre-selected from the plan,
and choosing an option moves the condition's status and writes an event.

**Reference screens (build to these):** read `docs/design/phase4.5-conditions/stage3/README.md` first, then match each PNG and go
through its *Must match* list. The HTML of the same name in `docs/design/phase4.5-conditions/stage3/html/` has the exact wording.
- `docs/design/phase4.5-conditions/stage3/screens/S3-02-round-plan.png` (next-step selects and their reasons)
- `docs/design/phase4.5-conditions/stage3/screens/S3-01-condition-items.png` (the next-step chips on the sheet)
- `docs/design/phase4.5-conditions/stage3/screens/S3-12-list-next-steps.png` (the Next step column and the new summary numbers)
Record the result under **"Visual check"** in the ticket file, screen by screen. A
difference that is not on that screen's *May differ* list is fixed, or it is a **STOP AND ASK**.

### LP-922 · Asking people · M

**What it is:** the drafts, using the Phase 4 email features as they are.
- **One borrower email per round** holding every open borrower item, in plain words: what, why,
  acceptable form (full PDF from the bank's website, all pages; signed and dated letter), and a due
  date. Items we already know will be needed (for example a final pay stub before funding) are
  included early.
- **One email per third party**, accumulating. The insurance email carries the lender's mortgagee
  clause from the letter. Contacts come from the file's participants; a missing address is asked once
  and remembered.
- **Questions and push-backs** go to the right underwriter from the lender contacts.
- **Reminders** are suggested from the date an email was marked sent. They are never sent
  automatically.
- **Privacy:** no full account numbers or SSNs in any email body (last four only). Documents come back
  through the **borrower upload link, scoped to this round's items**, or the file's inbox address.
- **Wording:** the "what and why" for each item comes from the library's template, with specifics
  filled in (amount, bank, last four, month). The AI polishes the wording and does not invent new
  requests.

**Done when** round 1 produces three drafts (borrower; title/attorney; LO), and marking them sent moves
the right conditions to *Waiting on …*.

**Reference screens (build to these):** read `docs/design/phase4.5-conditions/stage3/README.md` first, then match each PNG and go
through its *Must match* list. The HTML of the same name in `docs/design/phase4.5-conditions/stage3/html/` has the exact wording.
- `docs/design/phase4.5-conditions/stage3/screens/S3-04-borrower-email.png` (the borrower email)
- `docs/design/phase4.5-conditions/stage3/screens/S3-05-title-email.png` (the title/attorney email and the insurance note)
- `docs/design/phase4.5-conditions/stage3/screens/S3-06-underwriter-question.png` (a push-back to the underwriter)
Record the result under **"Visual check"** in the ticket file, screen by screen. A
difference that is not on that screen's *May differ* list is fixed, or it is a **STOP AND ASK**.

### LP-923 · Evidence arrives and is checked · L

**What it is:** when a document arrives for a condition item:
1. It is **linked** to the item (the needs engine's matching, plus the item's account last four,
   borrower and date range).
2. It is **checked by code** against what the item asked for:
   - all pages present;
   - the right account (last four) and the right borrower;
   - dated inside the **lender's** expiry dates from the letter;
   - the period asked for (for example "an additional consecutive month" means the month right after
     the one already in the file).
3. **Verification runs again** on the new document. Any new finding is linked to the condition, for
   example a deposit over 50% of monthly income (B3-4.2-02) or an NSF, with an explanation request
   drafted for the borrower.
4. If everything passes, the item is done. When every item on a condition is done, the condition
   moves to **Ready to send**. If a check fails, the item stays open with the reason, and a re-ask is
   drafted.

**Done when** a statement missing a page cannot reach Ready, a statement for the wrong account is
rejected with the reason, and a new large deposit on an uploaded statement is flagged before
submission.

**Reference screens (build to these):** read `docs/design/phase4.5-conditions/stage3/README.md` first, then match each PNG and go
through its *Must match* list. The HTML of the same name in `docs/design/phase4.5-conditions/stage3/html/` has the exact wording.
- `docs/design/phase4.5-conditions/stage3/screens/S3-07-evidence-checked.png` (checks on arrival, one failed)
- `docs/design/phase4.5-conditions/stage3/screens/S3-08-evidence-new-finding.png` (a new large-deposit finding)
Record the result under **"Visual check"** in the ticket file, screen by screen. A
difference that is not on that screen's *May differ* list is fixed, or it is a **STOP AND ASK**.

### LP-924 · The figures check (new) · M

**What it is:** conditions change numbers. For example, 7086 needs $27,148.22 more in verified assets,
and a new insurance premium changes the monthly payment and so the DTI. This ticket:
- **works out by code** what an accepted piece of evidence changes: verified assets, reserves, monthly
  payment, DTI;
- **compares with the DU tolerances** in B3-2-10 and says plainly when **DU must be re-run** (DTI now
  over 45% or up 3 points or more; income lower than stated; reserves short of what DU required and
  below 90% of it);
- **proposes** the change to the file's figures, with the evidence and the arithmetic. **She confirms
  it; the app never changes loan figures on its own.** Applying it uses the existing stated-financials
  edits (`api/stated_financials.py`) and reuses the existing DTI calculator.

**Done when** accepting the July and August statements for 7086 (asked in round 1) shows the new verified total against the
$38,210.40 required, and a synthetic DTI change from 44% to 46% is flagged "re-run DU" while 46% to 48%
is not (the guide's own examples).

**Reference screens (build to these):** read `docs/design/phase4.5-conditions/stage3/README.md` first, then match each PNG and go
through its *Must match* list. The HTML of the same name in `docs/design/phase4.5-conditions/stage3/html/` has the exact wording.
- `docs/design/phase4.5-conditions/stage3/screens/S3-09-figures-check.png` (old and new figures, DU re-run not needed)
Record the result under **"Visual check"** in the ticket file, screen by screen. A
difference that is not on that screen's *May differ* list is fixed, or it is a **STOP AND ASK**.

### LP-925 · Package, submit and lender settings · M

**What it is:**
- **One PDF per condition,** named with the lender's code (for example `7086 - Assets.pdf`), in the
  order of the sheet.
- **A one-line note per condition** saying how the evidence answers it. The AI drafts it, code checks
  its numbers, and she edits it.
- **Warnings** before submitting: prior-to-docs items still open, evidence expiring before the lender's
  close-by date, a DU re-run flagged by LP-924 and not done.
- **"Mark submitted"** moves the included conditions to *Sent to lender* and records what was sent.
  The next round's comparison (Stage 2) then shows what the lender cleared.
- **Per-lender upload fields:** UWM's note per condition; Sun West's comment plus "Name of Source"
  and "Date Verified" per condition (review change 7).
- **Built on the Conditions tab**, not the Lender package tab, which stays Phase 6's.
- **Lender settings:** the mortgagee clause, the upload cutoff (UWM 8 p.m. ET), who handles what, and
  review of lender codes the app hasn't seen before. Entered once per lender, used on every file.

**Done when** the test file's ready conditions produce a package with one named PDF and one note per
condition, and "Mark submitted" moves exactly those conditions to *Sent to lender*.

**Reference screens (build to these):** read `docs/design/phase4.5-conditions/stage3/README.md` first, then match each PNG and go
through its *Must match* list. The HTML of the same name in `docs/design/phase4.5-conditions/stage3/html/` has the exact wording.
- `docs/design/phase4.5-conditions/stage3/screens/S3-10-package.png` (the package on the Conditions tab)
- `docs/design/phase4.5-conditions/stage3/screens/S3-11-lender-settings.png` (lender settings, including the codes to review)
Record the result under **"Visual check"** in the ticket file, screen by screen. A
difference that is not on that screen's *May differ* list is fixed, or it is a **STOP AND ASK**.

---

## 6. What Stage 3 should produce for the test file's round 1

This is the target the tickets are tested against (fictional test data, same codes as your real
sheet):

| Code | What the lender asks | Items → who | Proposed option |
|---|---|---|---|
| 1228 | Final inspection (new construction) | Final inspection → appraiser via the lender's AMC | Lender is doing it: ordered through the lender *(confirm who orders it at UWM, §8 question 1)* |
| 7086 | Short funds: $38,210.40 required, $11,062.18 verified | $27,148.22 more in assets, 2 months of statements → borrower | Ask the borrower |
| 6132 | One more consecutive month, Capital One ending 9912 | The next month's statement → borrower | Ask the borrower (checked for the right month and account) |
| 6637 | Earnest money $2,850: source, receipt, clearance | Source (statement showing the funds) → borrower · receipt (copy of the check or the holder's statement) → title/escrow · clearance (statement showing the check cleared) → borrower | Borrower email + title email |
| 6178 | Insurance effective 09/30/2026; current policy if closing earlier | → none, if closing is on or after 09/30 | Push back: the letter says must not close before 09/30/2026 |
| 0132 | SC attorney preference disclosure with an approved attorney; matching wire instructions | Re-signed disclosure → borrower + LO · approved attorney → LO · wire instructions → attorney | LO email + attorney email |
| 1947 | Title: final seller CD with closing package | → title | Title email (prior to funding) |
| 1582 | Third-party processing invoice | → you | I'll do it |
| 0006 | Credit report invoice | → you | Already in the file (credit invoice 07/15, page 1) |
| 0007 | Final inspection invoice | → you, after 1228 | I'll do it, waits on 1228 |
| 6378 | Title: loan number on checks | → title (information to pass on) | Added to the title email |

**Result:** three drafts (borrower: 7086, 6132, 6637; title/attorney: 6637, 1947, 6378, 0132; LO:
0132), two of her own tasks (1582, and 0007 once 1228 is back), one already in the file (0006), one
push-back draft to the underwriter (6178), and one "lender is doing it" item (1228). No condition is left without a plan.

---

## 7. Reference screens

Drawn and in the repo, like Stages 1 and 2: `docs/design/phase4.5-conditions/stage3/`. The README
there has the rules every screen follows and a **Must match / May differ** list per screen. All data
is fictional (`uwm_round1`, borrower Alex Rivera).

| # | File (`screens/`, and `html/` with the same name) | Ticket | State |
|---|---|---|---|
| S3-01 | `S3-01-condition-items.png` | LP-919, 920, 921 | Detail sheet for 6637: reading, 3 items, who acts, next step |
| S3-02 | `S3-02-round-plan.png` | LP-920, 921 | "Plan for round 1", before confirming; 0132 needs confirming |
| S3-03 | `S3-03-confirm-reading.png` | LP-919 | "Please confirm how we read 0132" (0.64) |
| S3-04 | `S3-04-borrower-email.png` | LP-922 | Borrower email, round 1 (7086, 6132, 6637), due Thursday 09/03 |
| S3-05 | `S3-05-title-email.png` | LP-922 | Title/attorney email (6637, 0132, 1947, 6378), mortgagee clause note |
| S3-06 | `S3-06-underwriter-question.png` | LP-921, 922 | Push-back on 6178 to Lena Brennan (UW II) |
| S3-07 | `S3-07-evidence-checked.png` | LP-923 | 6132: August statement, page 6 missing, stays Waiting |
| S3-08 | `S3-08-evidence-new-finding.png` | LP-923 | 7086: $4,000 deposit over the $2,870.66 threshold, must be sourced |
| S3-09 | `S3-09-figures-check.png` | LP-924 | Assets $11,062.18 → $41,914.42, DTI 40.36% → 40.97%, no DU re-run |
| S3-10 | `S3-10-package.png` | LP-925 | UWM round 1 package: 6 conditions, 26 pages, 1228 warning |
| S3-11 | `S3-11-lender-settings.png` | LP-925 (codes: LP-918) | Admin → Lenders → UWM |
| S3-12 | `S3-12-list-next-steps.png` | LP-921 | The list with a Next step column, on 09/02 |

LP-918 has no screen of its own. Each UI ticket above lists its screens under **Reference screens
(build to these)**.

## 8. Decisions for you before we write the build spec

1. **Who orders what at UWM today on your files?** Final inspection (1228), title updates, insurance
   and payoffs: you, the LO, or UWM's Processor Assist? This decides which items are "ask" and which
   are "lender is doing it".
2. **Does the LO approve borrower emails before they go out?** If yes, the borrower draft goes to
   the LO first (an extra step in LP-922).
3. **Processor certifications** (for example a verbal VOE certification): do your lenders accept them
   from a processing company? This decides whether "I'll do it" can close an item with a signed
   certification.
4. **The note per condition:** do you want it in the upload package, in the lender portal's comment
   box (copy-paste), or both?
5. **UWM Underwriting+:** will your brokers use it? If many UWM files move to it, we should prioritise
   the lenders where you still do the work, and make "lender is doing it" the default for UWM
   third-party items.
6. **Library review:** can you spend about two hours reviewing the top 20 condition types when I send
   the table?

## 9. Size and order

- **Stage 3A** (read, plan, ask): LP-918 → LP-919 → LP-920 → LP-921 → LP-922. It has its own
  acceptance test: §6's plan and three drafts on round 1.
- **Stage 3B** (check, figures, package): LP-923 → LP-924 → LP-925. Its acceptance test is evidence
  checks, the figures check and the package on rounds 1–2.
- **Size:** larger than Stage 2, about the same as Stage 1. With the build-and-review loop, expect
  several days of Claude Code time, plus your library review (LP-918) and your answers to §8.
- **Before starting:** Stage 2's screen check and CI (which you're doing), and the follow-up tickets
  that are running now.

---

## Sources

- STRATMOR/Snapdocs borrower survey, via National Mortgage News: [Closing, document gathering issues weigh on borrower views of lenders](https://www.nationalmortgagenews.com/news/closing-document-gathering-issues-weigh-on-borrower-views-of-lenders)
- Fannie Mae Selling Guide [B3-4.2-02 Depository Accounts](https://selling-guide.fanniemae.com/sel/b3-4.2-02/depository-accounts) (large deposits)
- Fannie Mae Selling Guide [B3-4.3-09 Earnest Money Deposit](https://selling-guide.fanniemae.com/sel/b3-4.3-09/earnest-money-deposit)
- Fannie Mae Selling Guide [B3-3.1-04 Verbal Verification of Employment](https://selling-guide.fanniemae.com/sel/b3-3.1-04/verbal-verification-employment) (03/04/2026)
- Fannie Mae Selling Guide [B3-2-10 Accuracy of DU Data, DU Tolerances](https://selling-guide.fanniemae.com/sel/b3-2-10/accuracy-du-data-du-tolerances-and-errors-credit-report)
- FTC Safeguards Rule, [16 CFR Part 314](https://www.ecfr.gov/current/title-16/chapter-I/subchapter-C/part-314) (§314.4(c)(3) encryption)
- HousingWire: [UWM expands underwriter duties with Underwriting+ program](https://www.housingwire.com/articles/uwm-underwriter-program/); National Mortgage Professional: [UWM Combines Processing And Underwriting](https://nationalmortgageprofessional.com/news/uwm-combines-processing-and-underwriting-push-faster-closings)
- MBA NewsLink (May 2026): [From Condition Management to Condition Elimination](https://newslink.mba.org/mba-newslinks/2026/may/from-condition-management-to-condition-elimination-a-new-framework-for-mortgage-origination/)
- Sei AI: [Large-deposit sourcing with an AI agent under B3-4.2-02](https://www.seiright.com/blog/verification-of-assets-large-deposit-sourcing-ai-underwriting-fannie-bsa)
- Project research, September 2026: `phase4.5-condition-research.md` (processor actions, routine, UWM and Sun West specifics) and `phase4.5-appendix-C-condition-taxonomy.md` (condition types and rules)
