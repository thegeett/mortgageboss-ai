# Phase 4 execution protocol — the build/review loop

**This file is the rulebook for the Claude Code sessions building Phase 4. Read it before writing
any code, and re-read §2 before every commit.**

- **What to build:** [`phase4-build-plan.md`](phase4-build-plan.md) — tickets, order, per-ticket detail.
- **Why it is built that way:** [`phase4.md`](phase4.md) — architecture and decisions.
- **What it looks like:** [`phase4-mail-flows.md`](phase4-mail-flows.md) — the eight flows.
- **Where we are right now:** [`phase4-progress.md`](phase4-progress.md) — **the state file. Both
  sessions read it first and write it last.**
- **Repo conventions:** [`../../CLAUDE.md`](../../CLAUDE.md).

---

## §1 — Two sessions, one loop

Two Claude Code terminals against the same worktree. They never run at the same time.

```
  TERMINAL A — BUILDER                      TERMINAL B — REVIEWER
  ────────────────────                      ─────────────────────
  read phase4-progress.md
  pick the first PENDING ticket
  implement it, and only it
  write docs/tickets/LP-XXX.md
  make CI green
  commit
  mark AWAITING_REVIEW + commit SHA
  STOP  ──────────────────────────────────► read phase4-progress.md
                                            run the code-review skill on that SHA
                                            fix EVERY finding
                                            make CI green
                                            commit the fixes
                                            mark REVIEWED + fix SHA
  ◄──────────────────────────────────────── STOP
  resume: next PENDING ticket
```

**The strict rule, stated once:**

> A ticket is not finished when it is committed. It is finished when a **different session** has
> reviewed that commit with the code-review skill, fixed every finding, and committed the fixes.
> **The builder does not start the next ticket until the progress file says `REVIEWED`.**

No exceptions, including for tickets that look trivial. The point of the second session is that it
has no memory of the arguments the first one talked itself into.

---

## §2 — Rules for the builder session

1. **One ticket per commit cycle.** Never two, never a half. If a ticket turns out to contain two
   things, split it in the progress file and do the first.
2. **The plan is the spec.** Do not redesign. If the plan is wrong, record it in the ticket doc and
   in the progress file's **Notes** column, implement what the plan says, and let the reviewer
   escalate it.
3. **Never leave CI red.** `ruff`, `mypy --strict`, `pytest` for backend; `biome`, `tsc`, `build`
   for frontend. Run them before committing, not after.
4. **Every ticket writes `docs/tickets/LP-XXX.md`** in the existing house style — what was done,
   assumptions, decisions, what was deliberately not done. Look at `docs/tickets/LP-647.md` for the
   shape.
5. **Architectural decisions go in `decisions.md`** as a new ADR, not buried in a ticket doc.
6. **Stay inside the ticket's blast radius.** No opportunistic refactors, no drive-by fixes, no
   reformatting files the ticket does not touch. A large diff is a review that will not happen.
7. **Commit message:**
   ```
   LP-XXX: <one line, imperative>

   <2-5 lines: what changed and why. Name the design doc section it implements.>
   ```
8. **Terraform is never applied by a session.** `INFRA-1/2/3` are **HUMAN-GATED**: write the module,
   run `terraform plan`, commit the code and the plan output, and stop. A human applies it. Anything
   touching AWS state, DNS, or the SES sandbox request is a human action.
9. **Update `phase4-progress.md` last, as part of the same commit.**

---

## §3 — Rules for the reviewer session

1. **Start fresh.** Do not read the builder's reasoning; read the diff and the plan.
2. **Invoke the code-review skill** against the builder's commit. Review the diff, not the whole repo.
3. **Fix every finding.** Not triage — fix. If a finding is genuinely wrong, say so in the ticket
   doc with the reason; do not silently drop it.
4. **Check the ticket against its "Done when" clause** in `phase4-build-plan.md`. A ticket whose
   acceptance criterion is not actually met goes back to `PENDING` with a note, not forward.
5. **Three things to check on every Phase 4 ticket, regardless of what it touches:**
   - **Tenancy.** Anything reachable from an email address — or from a link in one — must derive
     `company_id` *from* the resolved loan file, never from a sender, a header or a guess.

     **Three places are allowed to invert the invariant, and they are named:**
     `services/inbound_routing.resolve_loan_file_by_address` (LP-805),
     `services/upload_links.resolve_link` (LP-815), and
     `services/mailbox_connections.resolve_connection_by_address` (LP-808) — **PROVISIONAL,
     awaiting a human's ratification; see the escalation in `phase4-progress.md`**.
     A **fourth** is a blocking finding.

     This said "exactly one place" until LP-815's review and "two" until LP-808. It was written
     before the secure upload link existed, and by the time that shipped the rule named one of the
     two things it governed — so a reviewer applying it literally would have had to call correct
     code a blocking finding. A governing rule that no longer matches the code is worse than no
     rule, because it is still obeyed.

     **WHO MAY SANCTION ONE — the part the last version left out, and the gap is mine.** LP-815's
     review wrote "if a fourth is ever sanctioned, amend this line in the same commit" in the
     passive voice and named no actor. LP-808's builder read that as a procedure it could carry out
     itself, which is a fair reading of what was written, and flagged the problem anyway. But a rule
     constraining builders that a builder may amend constrains nobody. So:

     - A **builder** may not sanction an inversion. It implements what the ticket needs, amends this
       line so the document does not go stale, and **escalates in the progress file for a human**.
     - A **reviewer** may not sanction one either, for the same reason one level up.
     - **A human ratifies it**, or the inversion comes out. Until then the line carries `PROVISIONAL`
       and the escalation stays open.

     The third entry below is `PROVISIONAL` on exactly those terms.

     What makes another one acceptable is not that it was needed. It is that it has the same
     shape: ONE function, every failure collapsing to ONE answer, and the row it resolves being the
     only thing that says whose the data is. Check a new one against those three, not against
     whether it seemed unavoidable.

     **The third is weaker than the first two and the difference is recorded rather than glossed.**
     LP-805 and LP-815 resolve a loan FILE; LP-808 resolves a COMPANY, because Route B's whole shape
     is that a customer's admin forwards their own alias to an address we minted for them, and mail
     arrives with no session and no user. A wrong answer from the first two misfiles one message; a
     wrong answer from the third puts a message in the wrong company's queue. Two things narrow that
     and neither removes it: the connection decides only the COMPANY — the FILE still comes from the
     routing ladder, whose rungs 3-5 are then scoped to that company — and the token is 128 bits
     matched on both halves of the address, exactly as `inbox_token` is.

     **It was a builder, not a human, who sanctioned the third.** The rule gave the procedure and
     the shape test, and both were followed; a person should still decide whether they agree, and
     it is in the progress file's escalations for that reason.
   - **No message content in logs.** Metadata only — never a body, never a subject, never a filename
     that came from outside.
   - **No AI in the decision path.** The model may classify and extract. It may not clear a
     condition, satisfy a need, or accept a document.
6. **Commit the fixes separately** as `LP-XXX: review fixes`, then mark `REVIEWED`.

---

## §4 — Running unattended

The point is that this finishes without someone watching it. So:

- **Never stop to ask a question.** Every decision this build needs has an answer in §5 or in the
  plan. If something is genuinely undecidable, mark the ticket `BLOCKED` with one line of reason in
  the progress file and **move to the next unblocked ticket** — do not idle.
- **Do not narrate.** No "let me now…", no summaries between tool calls. Work, then report once at
  the end of the ticket.
- **Batch independent tool calls** into one message. Never read the same file twice.
- **Search with `rg`**, not `grep -r` or `find | xargs`.
- **Run the test suite once per ticket**, at the end — not after every file. Target the affected
  tests while iterating (`pytest backend/tests/services/test_x.py`), full suite before the commit.
- **Do not re-read the design docs each ticket.** Read `phase4-build-plan.md` once per session and
  the specific ticket section when you reach it.
- **A ticket that runs long is a ticket that was too big.** Split it in the progress file rather
  than producing a 2,000-line diff.

---

## §5 — Decisions pre-made, so nothing blocks

`phase4.md` §E lists five open questions. Here are the answers to build against. Each is reversible
except where noted; each is recorded so the reviewer does not re-open it.

| Question | Build against this | Note |
|---|---|---|
| Which mail provider is the pilot customer on? | **Unknown — build Route B (forwarding) only.** Do not build Gmail API or Graph. | LP-816 stays scoped to a mailbox connection interface with no provider implementation |
| Is `Communication.body` encrypted at rest? | **No, in V1.** Routing and dedup columns must stay plaintext regardless, since `EncryptedString` is non-deterministic. | ⚠️ **Needs the user's explicit sign-off before the pilot touches real borrower NPI.** Raise it in the LP-803 ticket doc and add a backlog ticket for column-level encryption; do not let the run stall on it |
| How long is an inbound `.eml` kept? | **5 years**, matching the Closing Disclosure floor, with the legal-hold flag suppressing every purge path. | Sets the S3 lifecycle rule in INFRA-1 |
| Can a loan-file token cross `company_id`? | **No.** One company per file. The resolver raises on any other shape. | |
| Are borrowers told email is not a secure channel? | **Yes.** LP-817's templates carry the line, and LP-815's nudge steers to the upload link. | |

---

## §6 — Definition of done for Phase 4

Every row in `phase4-progress.md` is `REVIEWED`; CI is green on the branch; `decisions.md` has the
Phase 4 ADRs; every `LP-8XX` has a ticket doc; the INFRA tickets have applied plans; and the spec's
own Phase 4 testing checklist can be walked end to end on staging:

- a test document forwarded to a file inbox arrives and attaches correctly
- drafted emails read in Priya's voice
- reminder suggestions appear at the right times
- the timeline gives a complete picture of the file's interactions
