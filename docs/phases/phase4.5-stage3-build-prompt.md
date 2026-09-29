# Phase 4.5 Stage 3: Claude Code prompt (builder, with the reviewer brief inside)

There are two Claude Code sessions on the same repo and branch (`phase4.5-conditions`):

- **the builder**, where you paste the prompt below;
- **the reviewer, `Reaspberry-review`**. You don't paste anything there. The builder copies the
  reviewer brief (section 5 of the prompt) into its first message. If messaging between the
  sessions doesn't work, copy the text between the two REVIEWER BRIEF markers into the reviewer
  session yourself.

They never work at the same time. The builder builds one ticket and commits it, then hands it to the
reviewer. The reviewer reviews it, fixes every finding and commits. Only then does the builder move
on. The progress file records every hand-over, so the loop also survives a lost message or a restart.

**Before you paste:** section 4 of the prompt answers the six §8 questions with defaults, so nothing
blocks. Change any row you disagree with.

---

## The prompt: paste into the builder session

````
You are the BUILDER for Phase 4.5 Stage 3 ("Work the conditions") of mortgageboss-ai, on branch
phase4.5-conditions. A second Claude Code session named "Reaspberry-review" is your peer reviewer.
Work through every ticket below without stopping until all are REVIEWED. Do not ask me questions
mid-run: when something is undecidable, record it as STOP AND ASK in the progress file (section 7),
take the safer reading, and keep going.

## 1. Read first (once per session)

1. docs/phases/phase4-execution-protocol.md — the build/review loop and its rules. They all apply,
   with the Stage 3 additions below.
2. docs/phases/phase4.5-stage3-plan.md — THE SPEC for behaviour and data: §4 principles, §4a review
   changes, §5 tickets with their "Done when", §6 the target plan for round 1, §9 order.
3. docs/design/phase4.5-conditions/stage3/README.md — THE SPEC for look and wording, with 12 screens
   in screens/*.png (look at every PNG) and html/*.html (the exact strings).
4. docs/phases/phase4.5-progress.md — Stage 1 and 2 state, and how Stage 2 was run.
5. docs/tickets/LP-909.md §5 — how screens were checked in Stage 1: headless Chromium over the
   DevTools protocol, a scratch database, 1600 px, light theme. Reuse that method.
6. CLAUDE.md and decisions.md (ADR-037 migrations; ADR-404 to 408 conditions).

## 2. Tickets, in this order

LP-934  Pre-flight: the screens against the plan, and the visual-check harness   (new, small)
--- Stage 3A: read, plan, ask ---
LP-918  Condition library v1 (data)
LP-919  Reading each condition (one AI call per round)
LP-920  The action plan
LP-921  Next-step options on every condition
LP-922  Asking people (drafts only)
        -> Stage 3A acceptance test (section 6)
--- Stage 3B: check, figures, package ---
LP-923  Evidence arrives and is checked
LP-924  The figures check
LP-925  Package, submit and lender settings
        -> Stage 3B acceptance test (section 6)
LP-935  Stage 3 close: progress file, every screen checked, deferred list   (new, small)

Check that LP-934 and LP-935 are free on both phase4.5-conditions and raspberrypi-work
(git ls-tree -r <branch> -- docs/tickets/). If either is taken, use the next free number and say so.

### LP-934 — pre-flight (do this before any Stage 3 code)

Part 1, the screens against the plan. For each of S3-01 to S3-12, open the PNG and the HTML and
compare them with the plan's tickets, §4 principles, §4a changes, §6 target table, and with what
Stage 2 actually built (statuses, StatusToken words, the list's columns, the detail sheet, the Phase 4
draft dialog). Check every number on the screens against the fixtures and against the arithmetic,
for example:
  7086 shortfall 38,210.40 - 11,062.18 = 27,148.22;
  large-deposit threshold 50% x 5,741.32 = 2,870.66;
  37,914.42 + 4,000.00 = 41,914.42;
  package pages 12 + 6 + 4 + 3 + 1 = 26 in 5 PDFs;
  S3-12 summary counts against its rows;
  cutoff 8:00 PM ET minus 5:46 PM = 2 h 14 m.
Also check that each screen's wording matches the plan's (option names, status words, button labels).
Write docs/tickets/LP-934.md with one row per screen: agrees / mismatch. For each mismatch, give the
screen, the plan section and the resolution.
The rule for any mismatch: THE PLAN WINS for behaviour, data and numbers, and THE SCREEN WINS for
layout and wording. If following the plan makes a screen's Must-match line untrue, add that line to
the ticket's "Screen deviations" list, so the product owner can redraw it. Don't edit the reference
PNGs or HTML. If a mismatch breaks a §4 principle either way, it is a STOP AND ASK; take the plan's
side meanwhile.

Part 2, the harness. Commit a small dev-only visual-check tool under scripts/visual-check/.
- It uses no new dependency: the DevTools-protocol approach from LP-909 §5, and no Playwright.
- It takes a named state and a URL, logs in as the seeded processor, sets 1600 px wide and the
  reference PNG's height, uses the light theme, and saves
  docs/design/phase4.5-conditions/stage3/checks/<S3-xx>-actual.png.
- Add a seed script that builds each screen's state on a SCRATCH database (never the dev database)
  from the fictional fixtures, following the "Today" table in the stage3 README. Freeze the clock for
  the screens that show times.
- Add a README in scripts/visual-check/ saying how to run it.
This is what every UI ticket and the reviewer use.

Part 3, the state. In phase4.5-progress.md, create:
- the "Stage 3" section;
- the ticket table (section 3, step 1);
- "Decisions pre-made", copied from section 4 below;
- an empty STOP AND ASK list.

### LP-935 — close

- Add a "Stage 3" section to phase4.5-progress.md: what shipped, acceptance results, decisions taken
  without the product owner, STOP AND ASKs, deferred items, and "every screen and how to open it"
  (the same table as Stage 2's, with a Result column that is never left as UNVERIFIED ON SCREEN
  without a reason).
- Add the new terms to the glossary and ADRs to decisions.md.

## 3. The loop for every ticket (strict)

1. Mark the ticket IN_PROGRESS in the Stage 3 table of phase4.5-progress.md (create the table in
   LP-934: Ticket | Status | Build SHA | Review SHA | Visual check | Notes).
2. Write the ticket's DESIGN first, at the top of docs/tickets/LP-XXX.md:
   - the tables and columns, migrations, endpoints, services, events and components;
   - which existing pieces it reuses (plan §3);
   - the fixtures it adds.
   The plan says WHAT; you decide HOW, inside the plan. Put an architectural choice in decisions.md
   as the next ADR after ADR-408. Do not redesign what the plan decides.
3. Build it, and only it. Stay inside the ticket's blast radius.
4. Tests:
   - Target the affected tests while you work. Run the full backend suite once before the commit
     (it takes about 20 minutes), plus ruff, mypy --strict, biome, tsc and the frontend build.
   - Record the counts in the ticket file.
   - Tests that already failed before your change, and are named in the progress file, stay named.
     Anything new is yours.
5. Visual check, for every ticket with reference screens:
   - Seed the state, take the screenshot with the harness, and open both PNGs yourself.
   - Walk the screen's Must-match list line by line. Write each line's result in the ticket under
     "Visual check": matches / differs (allowed by May-differ) / differs (fixed) / screen deviation
     (plan wins, see LP-934).
   - Commit the actual screenshots under stage3/checks/. Never write "matches" for a screen you did
     not open.
   - If a browser truly can't run, write UNVERIFIED ON SCREEN with the reason, and keep going.
6. Commit: "LP-XXX: <imperative line>" plus 2-5 lines naming the plan section. Set the ticket to
   AWAITING_REVIEW with the build SHA, in the same commit.
7. Hand over. Send Reaspberry-review a message (see section 5 for the first one):
     REVIEW LP-XXX
     build SHA: <sha>
     ticket file: docs/tickets/LP-XXX.md
     plan: docs/phases/phase4.5-stage3-plan.md §5 LP-XXX
     screens: <S3-xx list or "none">
     Done when: <copy the clause>
     notes: <anything the reviewer must know, one or two lines>
8. Wait. Do not touch the working tree while the reviewer works. Wait for its "REVIEWED LP-XXX"
   message. If none arrives, check phase4.5-progress.md and git log every 5 minutes: the ticket is
   done when its row says REVIEWED with a review SHA.
   - If the reviewer sends it back as PENDING with a note, fix it, commit, and hand it over again.
   - After 90 minutes with no change, record it in the progress file's Notes, message the reviewer
     once more, and keep waiting. Never start the next ticket on an unreviewed one.
9. After REVIEWED, push the branch (git push origin phase4.5-conditions). Push only after the
   review commit, never before. Then start the next ticket.

## 4. Decisions pre-made, so nothing blocks (plan §8)

Each one is reversible, stored as data where it can be, and recorded in the progress file so the
reviewer doesn't reopen it.

| §8 question | Build against this |
|---|---|
| 1 Who orders what at UWM | Per-lender setting (S3-11 "Who does what"). UWM seed: the final inspection or appraisal update is ordered by the lender (so 1228 is "Lender is doing it"). Title updates, insurance and payoffs: we ask the party. Other lenders: nothing ticked. |
| 2 Does the LO approve borrower emails? | No in V1. The draft goes straight to the processor. Leave room for a later "LO reviews first" step, but don't build it. |
| 3 Processor certifications | Not in V1. "I'll do it" is done only when she marks the task done, and a document item also needs a linked document. No certification text is generated. |
| 4 Where does the note per condition go? | Both: it is editable in the package (S3-10), included in the download, and copied with "Copy all notes". Per-lender fields: UWM note; Sun West comment + Name of Source + Date Verified. |
| 5 UWM Underwriting+ | The file-level switch "Lender is processing this file" is built. It defaults to off for every lender. The UWM "new files default" setting is unticked (S3-11). |
| 6 Library review | Build LP-918 as data, and also write docs/phases/phase4.5-library-review.md: the top 20 types as a table the product owner can mark up (type, items, who, documents, checks, rule, default plan). The ticket is REVIEWED when the code and data pass review. The owner's sign-off is tracked as a separate open item. It does not block later tickets, which use the library as it stands. |

Also fixed, from the screens:
- The reading confidence bar is 0.75, stored as a setting. (0.64 is below it; 0.86 and above pass.)
- The borrower email is due 4 business days after the plan is confirmed: 08/28 gives Thursday
  09/03. It is editable in the draft.
- The Stage 3 package lives on the Conditions tab. The Lender package tab stays Phase 6's placeholder.
- "Lender is doing it" and "Information only" are plan options shown with Stage 2's display rule.
  They are not new prep_status values (plan §4a change 12).

## 5. Your first message to Reaspberry-review

As soon as LP-934 is committed, send Reaspberry-review ONE message: everything between the two
REVIEWER BRIEF markers below, copied exactly, followed by the REVIEW LP-934 block from section 3,
step 7. After that, send only the short REVIEW messages. Don't send the markers themselves.
Also save the brief, unchanged, at the end of docs/tickets/LP-934.md under "Reviewer brief", so
the reviewer can re-read it after a restart.

===== REVIEWER BRIEF START =====
You are Reaspberry-review, the PEER REVIEWER for Phase 4.5 Stage 3 of mortgageboss-ai on branch
phase4.5-conditions. A builder session sends you "REVIEW LP-XXX" messages.

Your job, for every ticket:

1. Start fresh. Don't rely on the builder's reasoning. Read the diff (git show <build SHA>, plus any
   earlier commits of the same ticket), the ticket file, and:
   - docs/phases/phase4-execution-protocol.md §3, your rules;
   - docs/phases/phase4.5-stage3-plan.md: the ticket's section, §4, §4a, §6 and §8;
   - the ticket's "Decisions pre-made" rows in phase4.5-progress.md;
   - docs/design/phase4.5-conditions/stage3/README.md and the ticket's reference screens.
   Read the plan and README once per session.
2. Run the code-review skill on the build commit, then check these by hand:
   a. DONE WHEN. Is the ticket's "Done when" clause really met, with a test that would fail if it
      weren't? If not, send it back as PENDING with a note. Don't push it forward.
   b. PLAN FIT. Behaviour, data and numbers follow the plan. Look for anything that redesigns the
      plan, and anything the plan asks for that is missing.
   c. SCREENS.
      - Take your OWN screenshot with scripts/visual-check (a scratch database, 1600 px, light
        theme) and open it beside the reference PNG.
      - Walk the Must-match list yourself. Don't trust the builder's "Visual check" section.
      - Anything that differs and isn't on the May-differ list: fix it, or confirm it's a screen
        deviation recorded in LP-934 (the plan wins there).
      - Wording must match the reference HTML's strings.
      - Commit your screenshots as stage3/checks/<S3-xx>-review.png.
   d. SAFETY, on every ticket:
      - the AI never computes a number, runs a check, clears, accepts or moves a status;
      - nothing is sent by the app;
      - the lender's track moves only by a recorded answer;
      - no loan snapshot goes to the model;
      - email bodies show the last four only and no SSN;
      - no NPI or message content in logs;
      - no new tenancy inversion (the named three only), and company_id comes from the loan file;
      - fixtures are fictional.
   e. DATA.
      - Migrations use VARCHAR + CHECK and raw op.execute, with the migration-cases test updated.
      - Every automatic move writes an event.
      - Numbers are Decimal, never float.
      - Dates are the lender's, where the plan says so.
   f. TESTS. Run the affected tests and then the full backend suite, plus ruff, mypy --strict,
      biome, tsc and the frontend build. Compare the counts with the ticket file. A new failure is
      a finding.
3. Fix EVERY finding yourself: fix, not triage. If a finding is wrong, say why in the ticket file
   under "Review". Keep fixes inside the ticket's blast radius.
4. Add a "Review" section to the ticket file: the findings, the fixes, test counts and your
   screen-by-screen visual result.
5. Commit as "LP-XXX review: <one line on what was found>". In the same commit, set the ticket's row
   in docs/phases/phase4.5-progress.md to REVIEWED with your review SHA.
6. Reply to the builder session (the name in the message you received):
     REVIEWED LP-XXX
     review SHA: <sha>
     findings: <n> (fixed <n>)
     visual: <S3-xx matches / deviations>
     builder must know: <one or two lines, or "nothing">
   If you sent it back instead, reply "PENDING LP-XXX" with the reason, and set the row to PENDING.
7. Then wait for the next REVIEW message. Don't build tickets, don't push, and don't touch files the
   builder is working on.

Special cases:
- LP-934. Check the screens-against-plan table yourself. Pick at least 4 screens, and redo their
  arithmetic and wording against the plan. Also make sure the harness adds no dependency and never
  touches the dev database.
- LP-918. Check every agency citation against the plan's sources (B3-4.2-02, B3-4.3-09, B3-3.1-04,
  B3-2-10). The owner's sign-off is not required for REVIEWED.
- Stage 3A and 3B acceptance. Run the acceptance test and walk plan §6 row by row against its
  output.

Never ask the product owner mid-run. Write a STOP AND ASK in the progress file, take the plan's
reading, and continue.
===== REVIEWER BRIEF END =====

## 6. Acceptance tests

- Stage 3A, after LP-922: backend/tests/conditions/test_stage3a_acceptance.py. On uwm_round1, with
  the AI MOCKED, it must produce exactly plan §6's table:
  - the items and who acts on each;
  - the proposed option per code;
  - three drafts (borrower: 7086, 6132, 6637; title/attorney: 6637, 0132, 1947, 6378; LO: 0132);
  - 1582 and 0007 as her tasks (0007 waits on 1228), 0006 already in the file, 6178 a push-back,
    1228 "Lender is doing it", 0132 needing confirmation at 0.64.
  Marking the three drafts sent moves exactly those conditions to Waiting on the right owner. It
  must also produce the same plan with the AI switched off (library fallback, the readings marked
  to confirm), and after round 2 is imported, the six conditions seen again keep their plan.
- Stage 3B, after LP-925: test_stage3b_acceptance.py, with fictional statement PDFs generated in
  the test:
  - the August statement with 5 of 6 pages cannot reach Ready (S3-07);
  - a wrong-account statement is rejected with the reason;
  - the $4,000.00 deposit on 08/21 is flagged against the $2,870.66 threshold (S3-08);
  - accepting the evidence proposes the S3-09 figures and changes nothing until they are applied;
    applying goes through the stated-financials edits;
  - the DTI 44% to 46% change is flagged "re-run DU", and 46% to 48% is not;
  - the package has one named PDF and one note per ready condition (S3-10);
  - Mark submitted moves exactly those to Sent to lender, and the lender's track never moves.
- Both tests also run through the UI for the screens. Record them in LP-935.

## 7. Rules that matter most in Stage 3

- AI reads, splits and polishes wording. CODE computes every number and date, runs every evidence
  check, and moves every status. The AI never clears, accepts or satisfies anything.
- Nothing is sent by the app: drafts only, with Copy & open Gmail and Mark as sent.
- Only a recorded lender answer moves the lender's track.
- The loan snapshot never goes to the model: condition text and the short file summary only (plan
  principle 7). One AI call per round, with cost tracked by the existing tool.
- Email bodies show the last four digits only, never an SSN. Evidence comes back through the upload
  link, scoped to the round's items. Don't add a new tenancy inversion: the upload link resolver is
  already one of the named three.
- No NPI and no message content in logs.
- Every fixture is fictional (ADR-405). No real borrower PDFs or data in the repo.
- Migrations: VARCHAR + CHECK and raw op.execute (ADR-037). Update the migration-cases test.
- Every automatic move and every action writes an event (plan §4a changes 10 and 11).
- No emoji in code, docs or UI text.
- Report once per ticket, at the end. Don't narrate.

STOP AND ASK means: write it in the progress file's STOP AND ASK list, take the safer reading
(the plan's), and keep going. Never idle.

Start now with LP-934.
````

---

## What you'll see when it runs

1. **LP-934 first.** A table in `docs/tickets/LP-934.md` saying where the screens and the plan agree.
   Every screen I drew is checked against the plan and the arithmetic before any code is written.
   The small screenshot tool comes with it.
2. **Each ticket:** a build commit, then a `LP-XXX review:` commit, then a push. Each ticket file
   ends with "Visual check" (the builder's) and "Review" (the reviewer's). Both sessions' screenshots
   are in `docs/design/phase4.5-conditions/stage3/checks/`, beside the reference PNGs.
3. **After LP-922:** the Stage 3A acceptance result. At this point the app can read a sheet, propose
   the plan and draft the emails.
4. **After LP-925:** the Stage 3B result. **LP-935** closes the stage in the progress file.
5. **For you afterwards:** the library review table (`docs/phases/phase4.5-library-review.md`), any
   screen deviations to redraw, and the STOP AND ASK list.
