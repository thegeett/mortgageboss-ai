# Communication v1 — draft only · LP-850 … LP-857

All eight tickets plus the epic index, in one file, for handing to Claude Code.

**Read the epic index first** — it carries the dependency order and the one coupling that will
break the feature if the tickets are split across sprints (LP-851 + LP-853).

Companion spec: `docs/domain/communication/comm-v1-draft-only-spec.md`.
When splitting this file back out: the epic index goes to
`docs/domain/communication/v1-epic.md`, each ticket to `docs/tickets/LP-8xx.md`.

---

## Epic index

Spec: `docs/domain/communication/comm-v1-draft-only-spec.md`.
Screens: artifact **"Draft Only Screens"**. Rationale: artifact **"Draft Only"**.

## The fence

**One version that does one thing: it writes drafts.** Nothing sends, nothing arrives, nothing
reminds. Delivery is a person with their own mail client, and every screen says so.

Out, and returning next phase: sending, receiving and inbound parsing, replies and threading, the
secure upload link, reminders (LP-814), `delivered` / `failed`, and anything that claims to know the
borrower received it.

## The eight

| # | Ticket | Blocked by | Size |
|---|---|---|---|
| LP-850 | Outstanding means outstanding, and one draft per party | — | large |
| LP-851 | One dialog, three doors | 850 | medium |
| LP-852 | A draft nobody knows about | 850 | small |
| LP-853 | The body becomes HTML the moment a person touches it | — | large |
| LP-854 | The toolbar Gmail has | 853 | medium |
| LP-855 | Copy and open, in one click | 853 | medium |
| LP-856 | A draft about nothing, and a button that makes it presentable | 853 | medium |
| LP-857 | Take the next phase off the page | — | small |

## Two independent chains, and one that can go first

```
LP-850 ──┬── LP-851 ── (LP-851 + LP-853 must ship together, see below)
         └── LP-852

LP-853 ──┬── LP-854
         ├── LP-855
         └── LP-856

LP-857 ── independent, start any time
```

**LP-850 and LP-853 are the two roots and touch nothing in common** — one is the draft lifecycle in
`email_draft.py`, the other is the body column and the editor. They can run in parallel from day
one, which is the whole reason the epic is cut this way.

**LP-857 is a net deletion and unblocks nothing**, so it is the safe thing to give a spare hand.

## The one coupling to watch

**LP-851 removes the per-document note form. LP-853 is what makes the draft body keep an edit.**

LP-839 built that note field *and* made it render — it is how a processor says "the March statement
specifically, not February". Remove it while `_regenerate` still overwrites the body on every append
and the feature is a regression, not a simplification.

**Ship them together or ship neither.**

## The decisions these encode

Recorded here so nobody re-litigates them from a screenshot:

1. **Draft membership is not the source of truth for what is outstanding.** The needs list is.
   Both of the flow defects trace to this one confusion (LP-850).
2. **One open draft per party, enforced in the service.** Not a warning, not a convention — the
   second open draft cannot be created (LP-850).
3. **"Mark as sent" is a claim, not an event.** Nothing observed a send, so the record is attributed
   — `Marked sent by Priya · Tue 16:41` — and it never moves a need to `received` (LP-850, LP-855).
4. **Generated bodies stay plain; a human edit makes them HTML.** `body_format` is also the
   `body_edited` flag. One fact, one place (LP-853).
5. **Three of Gmail's controls are declined** — font family, text colour, alignment — and the
   reasons are in LP-854, not in somebody's memory.
6. **No compose route carries formatting.** So the button copies *and* opens, with the body left
   empty (LP-855).
7. **No Send button, not even disabled** (LP-855, LP-857).
8. **The party is a column, never a heading.** A heading is a region that can be scrolled past
   (LP-852).

## What "done" looks like

A processor opens a file, clicks Request all, gets one dialog that tells them a draft is already
open and what is in it, adds to it, writes two sentences of their own in a real editor, clicks
**Copy & open Gmail**, pastes, sends, comes back and marks it sent — and the next request knows
which documents have since arrived.

Nothing in that sentence requires the app to send or receive anything.


---

# LP-850 — outstanding means outstanding, and one draft per party

Status: spec. First of eight. **Blocks LP-851 and LP-852.**

## The report

> "Le's think about the flow of communication page. I think current flow is buggy. When processor
> click on individual document request button it check if there is any draft open, if so it adds
> requested document ask on that draft. If no draft is open it creates new draft."
>
> "How we would know whether previous draft is satisfied by receiving documents or not? Because we
> are not going to build or make it live receiving an email with document by email from borrower or
> other parties."
>
> "No two open draft for same party. Keep it simple."

## Two defects, one root cause

**Draft membership is being used as the source of truth for what is outstanding.** The needs list
already knows — it is literally the `needs_action` group — and the draft query re-derives the same
fact from a different table. The two disagree.

### D1 — a new draft supersedes nothing

LP-832 removed the `uq_communications_open_draft` partial unique index, so each request creates a
**new** draft carrying `outstanding + fresh`. Nothing retires the one it replaces. N clicks leave N
live, valid, sendable drafts with overlapping contents. Send Draft 1 and then Draft 3 and the
borrower is asked for the same bank statement twice.

The screenshot this produces is four rows reading *"A document request is being prepared"*, same
subject, same recipient, differing only by a timestamp — and **nothing marks 1 and 2 obsolete,
because nothing knows they are.**

### D2 — the outstanding set never looks at whether the document arrived

`_outstanding_needs` (`email_draft.py:866`) selects needs joined to a `Communication` where:

```python
Communication.loan_file_id == loan_file_id,
Communication.status == CommunicationStatus.DRAFT,
Communication.template_key == draft_template_key(party),
Communication.deleted_at.is_(None),
NeedsItem.deleted_at.is_(None),
```

**There is no filter on `NeedsItem.status`.** A need that is `received`, or `verified`, stays in the
outstanding set for as long as some unsent draft carries it — and is therefore carried into the next
draft and asked for again.

It only *looks* correct because marking a draft sent also clears the set: the needs drop out because
of **the send**, not because the document arrived. The two causes coincide often enough to pass a
demo and diverge in real use.

**This bites hardest in exactly our situation.** With no live inbound email, documents arrive by
manual upload or by the secure link — paths this query never looks at. And borrowers send things
unprompted, or after a phone call, so a document arriving *before* its request went out is ordinary
rather than rare.

## Decisions

**1. The outstanding set comes from need status, not draft membership.**

`_outstanding_needs` gains a filter: carry a need only while its status is `pending`, `requested` or
`rejected`. Anything `received` or `verified` drops out the moment the document lands — by upload,
by the secure link, or by a processor marking it — because the need's own status is what moved, and
the need's own status is now what is read.

The outstanding set becomes **identical to the `needs_action` group the screen already shows**. One
fact, one place.

**2. One open draft per party, enforced in the service.**

Not in the UI. LP-832's index could not express this because it keyed on the file, and a title
company's draft and a borrower's draft are both legitimately open at once. The constraint is
`(loan_file_id, party, status=DRAFT, deleted_at IS NULL)`.

**3. A request against an open draft has exactly two outcomes.**

Append to it, or mark it sent and create a fresh one. There is no "create a second open draft",
which is what removes D1 by construction rather than by asking a processor to be careful.

## The endpoint

The UI must not have to ask twice. A request returns either the draft it created, or a
**decision-required** response naming the open draft, its contents and its age — enough for
LP-851's dialog to render without a second round trip.

```
POST /loan-files/{id}/communications/requests
  { needs_type[], on_conflict: null | "append" | "mark_sent_and_new" }

201 { drafts: [{party, draft_id, needs_added[]}] }
409 { decisions_required: [{party, open_draft: {id, created_at, needs[], body_edited}}],
      would_create: [{party, address, needs[]}] }
```

`would_create` carries the parties that need no decision, so LP-852 can name them in the same
dialog. A 409 writes nothing.

## What it must not break

- **LP-832's composing rule stands.** A new draft still carries everything outstanding plus the new
  items. What changes is *what counts as outstanding*, and what happens to the draft being replaced.
- **LP-821's evidence record.** A superseded or marked-sent draft is never deleted. `mark_sent` is
  the existing transition, not a new one.
- **`party_requests.PARTY_ROLE` still excludes `PROCESSOR`**, deliberately — mapping it to anything
  would turn "we fetch this" into "we email somebody about it".
- **LP-835's party drafts stay reachable** from the same list and the same modal.

## Acceptance

1. **The test that fails today:** request a document, mark the need `verified` while the draft is
   still unsent, request a second document. The second draft contains **only** the second document.
2. Two requests in a row for the same party produce **one** draft, not two.
3. `on_conflict: null` with an open draft writes nothing and returns 409 with the draft's contents.
4. `mark_sent_and_new` leaves the old draft `sent` with its `requested_at` stamped and its needs
   intact, and the new draft carries only what is still outstanding.
5. A request spanning the borrower and the title company returns one 409 listing the borrower's open
   draft and the title company under `would_create`.
6. Marking a draft sent does **not** move any need to `received`. Sending is not receiving.


---

# LP-851 — one dialog, three doors

Status: spec. **Blocked by LP-850.** Screens 3, 4, 5, 6, 7.

## The report

> "If any draft is open then we should give pop up message on each request button click with message
> there is open draft, append or create new draft, with these action button. If user click append
> then append it otherwise create new draft. Message should also say mark sent if you want to create
> new one otherwise."
>
> "Currently if we select individual request button is ask to write a message lets remove that,
> instead have this pop up. And Request all button have one pop itself let's add this message."
>
> "Request documents button on current communication page should remain same."

## The dialog

One component, three callers, one 409 shape from LP-850 behind it.

> **There is already an open draft to the borrower**
>
> Created Tue 14:02, asking for: `Bank statement — March` `Pay stub`
>
> Add **Homeowner's insurance declaration** to it — or, if you have already sent that draft from
> your mail client, mark it sent and start a new one.
>
> `[Cancel]` · `[I've sent it — mark sent, start new]` · `[Add to the open draft]` ← primary

**It names the draft by its contents, not by an id.** "There is an open draft" is not enough to
decide with; three document names and a timestamp are, and they are what a processor remembers.

**Marking sent is a button, not advice.** Advice that requires closing the dialog, finding the
draft, marking it and coming back will not be followed on a busy Tuesday.

**"I've sent it", not "Mark as sent".** Nothing in the app observed a send — the record it writes
reads `Marked sent by Priya · Tue 16:41`. A neutral label invites pressing it to dismiss the dialog,
which is how `requested_at` ends up stamped on a message that never went out.

## When one request touches two parties

One dialog, **a row per party** — never two dialogs in sequence. A processor who has just confirmed
five documents and is then asked a second question clicks the primary without reading it, which is
exactly how the wrong draft gets chosen.

A party under `would_create` gets a row with **no buttons**: it needs no decision, but the processor
must leave knowing a second message exists. That is LP-852's rule appearing here.

## The three doors

| Door | File | Change |
|---|---|---|
| Individual request on a finding | `verification/rule-finding-actions.tsx` | **The `request-docs` form is removed.** `Request` fires the rule directly. |
| "Request all N" | `verification/bulk-request-button.tsx` | Its existing confirm **grows the party blocks and the extra button**. Unchanged when nothing is open. |
| "Request documents" | `communication/compose-request-dialog.tsx` | **Untouched.** The catalog, the needs-first ordering and the "already requested" markers all stay. |

### What removing the note form costs, said plainly

LP-839 built that field *and* made it render — the note appears under its own document in the email,
which is how a processor says "the March statement specifically, not February". Removing it means
that sentence has to be typed into the draft body instead.

**That is only acceptable because LP-853 makes the body keep an edit.** These two tickets ship
together or the feature is a regression.

## The edited-draft warning

When the 409's `body_edited` is true, the dialog gains a block **above** the buttons:

> **You have edited this draft.** Adding a document rewrites the message from the template, and your
> changes — including *"March statement only, not February"* — will be lost. Copy anything you want
> to keep first.

**It quotes the processor's own first edited line back at them.** "Your changes will be lost" is
abstract and gets dismissed; their own sentence does not. The primary becomes `Add anyway`.

## What it must not break

- **LP-839's row status.** `documents_requested`, the "requested — in the latest draft" line, and
  LP-841's per-party "requested — in a draft for the title company" clause all still render. Only
  the input form goes.
- **LP-833's catalog dialog** keeps its own "already requested" marking at selection time. Saying it
  before they pick is cheaper than saying it after, and this ticket does not move that.
- Nothing here decides anything. Every branch is LP-850's 409; the dialog renders it and sends back
  one `on_conflict` value.

## Acceptance

1. Requesting a document with no open draft shows **no dialog** and creates the draft.
2. Requesting with an open draft shows the dialog, and **Cancel writes nothing** — verified against
   the database, not the toast.
3. "Request all" shows **one** dialog, not two.
4. A borrower + title company selection shows two rows, one with buttons and one without.
5. `body_edited` shows the warning with the processor's own text quoted in it.
6. The `request-docs` form no longer exists, and `NeedsItem.description` is no longer written from
   that path.


---

# LP-852 — a draft nobody knows about

Status: spec. **Blocked by LP-850.** Screen 1.

## The report

> "you are displaying draft and Not from the borrower-2, but in some instance Not from the borrower
> go bottom of the list and processor may not realize that draft has been created for non borrower.
> instead what if we make single list, containing some indication of new draft added recently. no
> bucket. Just user see the list with indication borrower non borrower."

And, on the request flow:

> "Always name the party draft."

## The failure this closes

A message the system wrote, addressed to somebody the processor did not expect, **sitting where they
will not look.** Two shapes of the same bug:

1. **The buckets.** Party tabs, or party group headings, put a title-company draft below the fold. A
   heading is a region that can be scrolled past. The processor never learns it exists, never sends
   it, and the title company is never asked.
2. **The toast.** `"Draft prepared"` — which draft, to whom? LP-835 already fixed one version of
   this: the panel used to say *"Send it from the document request above"*, and the draft above was
   the borrower's, so a processor following that instruction emailed the wrong person.

## Decisions

**1. The party is a column on every row, never a heading.**

One list, in one time order, with `Borrower` / `Title co.` / `Lender` in a fixed-width column on the
left of each row. A column cannot be scrolled past. This is the single change that closes shape 1.

**2. Every toast names the party and the count.**

`"Draft to the title company — 1 document"`, `"Draft to the borrower — 3 documents"`. Never
`"Draft prepared"`. The party is the part a processor cannot infer.

**3. The row says what is inside without being opened.**

Count *and* the first few document names. Four rows reading *"A document request is being
prepared"* is the screenshot that started this.

**4. A "since you last looked" dot, not an unread badge.**

Nothing is received in this version, so "unread" would be a claim about somebody else's behaviour.
The dot marks drafts created since this processor last opened the page, and clears on open.

**5. Status is a word and a colour, never a colour alone** — and the word is attributed.
`Draft` · `Sent by Priya · Mon 16:41`. Not `Sent`.

## What it must not break

- LP-831's list-leads layout and the modal it opens.
- LP-843's `party` column, which is where the column's value comes from — this ticket adds no new
  source of truth for who a draft is to.

## Acceptance

1. A title-company draft is visible **without scrolling past a heading** on a file with ten drafts.
2. Every creation path's toast names a party. Grep for `"Draft prepared"` returns nothing.
3. The dot appears on a draft created by another session and clears when the row is opened.
4. A screen reader reads the party before the subject on every row.


---

# LP-853 — the body becomes HTML the moment a person touches it

Status: spec. **Blocks LP-854. The one with real risk in it.**

## The report

> "I did not like current rich text area, It just has Bold and Bullet option. Check how many Gmail
> provide while compose, and make it like that."
>
> "Text area should be reach text... Make sure when user copy it and paste it it should preserve
> text formatting specially in email client, Outlook/gmail."

## This reverses LP-849's storage decision, with the benefit of having seen it

LP-849 decided: *"the body column stays one plain string; the editor converts on load and serialises
on save. Not HTML-in-the-column."* That was the right call **for the schema it shipped** —
paragraphs, bullets, bold — and it was chosen precisely so the editor could not produce something
the converter silently drops.

Underline, links, ordered lists, indent and block quotes **cannot round-trip through that string.**
So the toolbar request is a storage request, whether or not it was meant as one.

LP-849 listed four costs of storing HTML. **Three are avoidable and one is real:**

| LP-849's objection | Verdict |
|---|---|
| "every backend template would have to emit HTML (all of them, each a new ADR-401 version and fingerprint)" | **Avoided.** Templates keep emitting plain text. See the decision below. |
| "`finalise_draft_body`'s placeholder pass would run over markup" | **Avoided.** Placeholders resolve while the body is still plain. |
| "`mailto:` needs a generated plain-text downgrade" | **True, and cheap.** Derived on demand, never stored. |
| "the send record — which must be *what went out* — becomes a format no existing test reads" | **True.** This is what the format column is for. |

## The decision: a format column, and generated bodies stay plain

Add `Communication.body_format` — `plain` | `html`.

- **A generated draft is `plain`.** Templates, `finalise_draft_body`, ADR-401 fingerprints,
  `_regenerate` and LP-849's round-trip fixed point are all **untouched**. This is what kills
  objection 1: nothing on the backend learns to emit HTML.
- **The first processor edit stores HTML** and flips the column. From then on the body is authored
  content and the backend treats it as opaque.
- **`body_format == 'html'` IS LP-851's `body_edited` flag.** One fact, one place — **do not add a
  second column.** "A machine wrote this" and "it is still plain" are the same statement, and
  storing them twice is the pattern that has bitten this codebase seven times (A22).
- **`_regenerate` refuses on an `html` body.** LP-851's warning dialog is the user-facing half of
  the same rule; this is the half that cannot be clicked past.
- **Plain text is derived, never stored.** `plain` bodies are used as-is; `html` bodies are stripped
  on demand for `mailto:` and LP-855's compose links. Two stored copies of one message is the same
  anti-pattern again.

## Sanitisation is in this ticket, not a follow-up

`email-body.ts` is safe **by construction** today: it escapes every character that could begin
markup *before* emitting a single tag, so there is no passthrough to leave open and no sanitiser
whose rules have to keep up with a renderer. Its own comment says so, and it was right.

**Storing author HTML ends that property.** An allowlist on the way in replaces it — server-side,
matching the editor schema exactly, with the same tag set LP-854 enables and nothing else. A
sanitiser added later is a window in which every draft written is untrusted, so it ships here.

Attributes are the part to get wrong: `href` on `<a>` restricted to `http`, `https` and `mailto`
only. Nothing else survives — no `style`, no `class`, no `on*`.

## What it must not break

- **`emailBodyToHtml` stays the single renderer for the `plain` path.** The editor and the reader
  must not be able to disagree, which is LP-849's rule and still holds for every generated draft.
- **LP-844's clipboard pairing.** `text/html` + `text/plain` together in one `ClipboardItem`, with
  the `writeText` fallback. HTML alone fails silently in Chromium. Do not touch `copy-rich.ts`
  beyond feeding it the right source.
- **The mail-client-safe output.** Bare `<p>`, `<ul>`, nested `<ul>`, `<strong>` — **no classes, no
  stylesheet dependency**, because Outlook on the desktop renders with Word's engine and discards
  most CSS. Whatever LP-854 adds must hold to this.
- **LP-849's round-trip fixed point** still guards the `plain` path and must still pass.

## Acceptance

1. A generated draft stores `body_format = 'plain'` and a body byte-identical to today's.
2. Opening a generated draft and **not typing** leaves it `plain`. Focus is not an edit.
3. The first real edit flips it to `html` and `_regenerate` then refuses.
4. `mailto:` and the compose links carry correct plain text from both formats.
5. A body containing `<script>`, `onclick=`, `style=` or a `javascript:` href is stored stripped —
   tested server-side, with the request built by hand rather than through the editor.
6. Every LP-849 round-trip test still passes on the `plain` path.
7. Migration: every existing row is backfilled `plain`. No existing draft changes.


---

# LP-854 — the toolbar Gmail has

Status: spec. **Blocked by LP-853.** Screen 2.

## The report

> "I did not like current rich text area, It just has Bold and Bullet option. Check how many Gmail
> provide while compose, and make it like that."

## Gmail's bar, button by button

| Gmail has | Take | Why |
|---|---|---|
| Undo · Redo | **yes** | Table stakes anywhere people type paragraphs. Tiptap ships `History`. |
| Font family | **no** | A document request in Comic Sans is a real outcome, and the font does not survive `mailto:` or a paste into a themed client anyway. The reader's own default is the right font. |
| Text size (S/M/L/Huge) | **no** | Harmless and unused in a business letter. Cheap to add later if anyone asks. |
| **Bold** · **Italic** | have them | LP-849. |
| **Underline** | **yes** | New. Survives a paste into Outlook and Gmail. |
| Text colour · highlight | **no** | **Colour means status in the Ledger.** A processor colouring a sentence red inside a compliance record is a claim nobody intended, and it is the one addition that could contradict a status glyph sitting two inches away. |
| Align left / centre / right | **no** | Centred body text in a letter is a formatting accident. Keeping the button out is cheaper than repairing the output. |
| **Numbered list** | **yes** | "Send these three, in this order" is a thing processors write. |
| Bulleted list | have it | LP-849. |
| **Indent more / less** | **yes** | It is how LP-846's nested detail block is built. The structure is already in the output; give it a button. |
| **Quote** | **yes** | Quoting the borrower's own sentence back is common, and the Ledger already reserves Plex Serif italic for verbatim quotation — so the mark has a meaning here, not just a style. |
| **Link** | **yes** | Gmail keeps it in the footer rather than the format bar. Most-wanted, and absent from the schema today. |
| **Remove formatting** | **yes** | The repair tool for everything pasted in from elsewhere. Without it a bad paste is unfixable and the processor retypes the message. |

Net: **seven added, three declined.** Declining three is the argument, not an omission — record it
so the next person does not re-litigate it from the screenshot.

## The schema and the sanitiser are the same list

Tiptap extensions, LP-853's server allowlist and `emailBodyToHtml`'s output must name the **same
tags**. LP-849's own notes record formatting vanishing on save when two of the three drifted:
`htmlToEmailBody` stripped `**` from any `<strong>` ending in a colon while the renderer re-bolded
only a capitalised run of 3–41 characters, and everything in the gap lost its asterisks.

**Derive the list once and import it into all three places.** Not three copies that agree today.

## Links are the one element with a security dimension

A link in an email to a borrower is a phishing surface if we let it be. `href` accepts `http`,
`https` and `mailto` only — enforced in the editor **and** in LP-853's sanitiser, because the editor
is not a security boundary. Display text defaults to the URL; a link whose text is a *different*
URL is the classic deception and should be left alone rather than cleverly rewritten.

## What it must not break

- **No classes, no inline styles, no stylesheet dependency in the output.** Outlook desktop renders
  with Word's engine. Every new mark must be a tag Word keeps: `<u>`, `<ol>`, `<li>`,
  `<blockquote>`, `<a href>`.
- LP-844's `text/html` + `text/plain` clipboard pairing.
- **No markup visible to the processor, anywhere.** LP-849's requirement: a `**` on screen is a
  failure, and so is a raw `<a href>`.

## Measurement

The communication route was **195 kB first-load** at LP-849. Re-measure and state the new number in
the PR — `Link`, `Underline`, `OrderedList` and `Blockquote` are small, `History` is not free, and
the number is only meaningful if somebody keeps writing it down.

## Acceptance

1. Each of the seven marks round-trips: apply → save → reopen → still there, and the stored HTML
   contains only allowlisted tags.
2. Paste a styled block from Word or a web page → **Remove formatting** returns it to plain
   paragraphs with no residue.
3. A `javascript:` href is rejected by the editor **and**, sent directly to the API, by the
   sanitiser.
4. Copy a message using all seven and paste into Gmail and Outlook on the web: bold, italic,
   underline, both list types, indent, quote and the link all survive. **Manual, and recorded.**
5. No markup is visible in the editor at any point.


---

# LP-855 — copy and open, in one click

Status: spec. **Blocked by LP-853.** Screens 2 and 10.

## The report

> "On draft how many action button? On Send through your Email client, can we open Gmail or outlook
> compose page? How we should know whether to open gmail or outlook?"

## Yes to the first. No to the thing it implies.

Every web compose route exists and takes `to`, `subject` and `body`:

| Route | URL |
|---|---|
| Gmail | `https://mail.google.com/mail/?view=cm&fs=1&to=…&su=…&body=…` |
| Outlook — work | `https://outlook.office.com/mail/deeplink/compose?to=…&subject=…&body=…` |
| Outlook — personal | `https://outlook.live.com/mail/0/deeplink/compose?to=…&subject=…&body=…` |
| Desktop default | `mailto:…?subject=…&body=…` |

**Every one of them takes the body as plain text.** `mailto:` is plain by RFC 6068 and the three web
routes are no better. There is no route that carries the formatting LP-854 just built.

## So the button does both things

**Copy the rich body to the clipboard, and open the compose window with To and Subject filled and
the body left empty**, then say so: *"Paste into the message — ⌘V"*.

Filling the body with the stripped plain-text version instead would hand the processor a message
that **looks finished** and has quietly lost its structure — worse than an empty one, because
nothing prompts them to notice.

Leaving it empty also retires the length problem: `mailto_max_chars` exists because a long body
overflows the URL, and there is no longer a body in the URL. Keep the ceiling as a guard on subject
plus address; stop hiding the button because a message is long.

## Which client — it is a setting, because nothing can detect it

No browser API reports this. So: a **per-user preference** (`preferences` already exists — one
string), asked once on the first draft.

- **Seed the default from their own sign-in domain.** `@gmail.com` or a Workspace domain
  pre-selects Gmail; `@outlook.com` or a Microsoft 365 tenant pre-selects Outlook. It is a guess, so
  **it moves a radio button and says why** — it never decides.
- **"Whatever this computer opens" (`mailto:`) is the safe answer** and the fallback for anyone on
  Apple Mail, Thunderbird or a locally installed Outlook. It is what "Not now" selects.
- Until they choose, the draft button reads **Copy & open mail app**.

## The buttons on a draft — the answer to "how many"

`[Copy & open Gmail]` · `[Copy message]` · `[Mark as sent]` … `[Delete]`

Three and a quiet fourth.

1. **Copy & open <client>** is primary and is the whole send path. The label carries the chosen
   client, so the button says what will happen before it happens.
2. **Copy message** stays for anyone doing it their own way — and is the fallback when the popup
   blocker eats the compose window.
3. **Mark as sent** is the claim, attributed: `Marked sent by Priya · Tue 16:41`. In this version it
   starts no clock, because there are no reminders.
4. **Delete** is quiet and on the far side. It destroys the record LP-821 wants.

**There is no Send button, not even disabled.** `mail_transport` is an interface with no provider
behind it. A greyed-out Send is a promise this version cannot keep and the first thing a processor
will click.

## What it must not break

- LP-844's clipboard pairing, which is what makes the copy half work at all.
- The `mailto:` route stays, and stays honest about being plain text.
- Nothing here marks anything sent. Opening a compose window is not evidence.

## Acceptance

1. Each of the four routes opens with To and Subject correct and the body **empty**.
2. The clipboard holds `text/html` and `text/plain` after the click, verified by pasting into Gmail
   and Outlook web — bold, lists and links intact.
3. A blocked popup leaves the clipboard populated and tells the processor the copy succeeded.
4. Preference persists across sessions and is changeable.
5. A processor who never answers the picker gets `mailto:` and a button reading
   **Copy & open mail app**.
6. Subject and address are URL-encoded correctly, including `+`, `&` and non-ASCII names.


---

# LP-856 — a draft about nothing, and a button that makes it presentable

Status: spec. **Blocked by LP-853.** Screen 8.

## The report

> "Also let's give option for processor to compose new free email, where they just write email and
> there will be AI button clicking on it, AI make the message more professional."
>
> "Also simple create email draft button for new free draft with AI composition."

## The free draft

A third button on the Communication page — **Compose** — producing an ordinary draft with **no needs
attached**. Same list row, same modal, same buttons, an empty "What it asks for" block.

`custom.v1` already exists as a template key. **This is not a second kind of object**, and it must
not become one: a free draft that needed its own list, its own modal or its own send path would
double every future change to drafts.

**The recipient is typed, not derived.** There is no party to look up an address for. Editable,
defaulting to the borrower, and **nothing written back to the file's party addresses from here** —
an address typed for one message is not a fact about the file.

## The AI button

One control in LP-854's toolbar: **✦ polish**. Violet, because violet in the Ledger means
**provenance — a model touched this** — and never status. Available on any draft, not only a free
one; a generated request a processor has rewritten by hand is exactly where it is wanted.

### It proposes; it does not replace

The rewrite is shown as a **proposal**, with the original held, and two actions: **Keep this** and
**Undo — put mine back**.

A rewrite that lands silently on save is a message going out in words nobody read — and the
processor is the one who will be asked about those words later. One click to accept, one to discard,
and the original recoverable until they choose.

### It fails visibly or not at all

`email_draft_enabled` is off in every environment today. LP-833's compose toast is already careful
about this — it says *"using the standard wording"* rather than claiming a model wrote something it
did not — and this button follows the same rule.

**When the model is unavailable the button says so and leaves the text alone.** It never returns
something subtly different and calls it polish. A silent degradation here is worse than an error,
because the processor cannot tell which version they are looking at.

### What it is allowed to change

Tone, grammar, structure, greeting and sign-off. **Not facts.** The prompt is constrained to
rewriting what is there — it does not add a deadline, a document, an amount or a date that the
processor did not write. A polish that invents "by Friday" is a commitment the file did not make.

## What it must not break

- The draft list, the modal and LP-855's buttons are shared. No branch on "is this a free draft"
  beyond the empty needs block.
- LP-853's format rule: a polished body is authored content, so it stores `html` and
  `_regenerate` refuses it — which is correct, because there is nothing to regenerate.

## Acceptance

1. Compose creates a draft with zero needs that appears in the list and opens in the same modal.
2. Polish with the flag off returns an error the processor can read, and the text is unchanged.
3. Polish with the flag on shows a proposal; **Undo** restores the original exactly, including
   formatting.
4. Accepting stores `body_format = 'html'`.
5. A typed recipient does **not** appear in `party_requests` afterwards.
6. A polish prompt given a body with no dates returns a body with no dates. Checked, not assumed.


---

# LP-857 — take the next phase off the page

Status: spec. Net deletion. Screens 1 and 9.

## The report

> "In this version I want to limit to draft only, no reminder or nothing... No receiving, sending,
> secure upload link, reply email and all. We will do it in next phase."
>
> "No Write to another party in v1."

## The page must not offer what the version cannot do

Half the confusion in the current Communication page comes from controls that exist as an interface
with **nothing behind them**. `mail_transport` is the standing example — *"an interface with no
provider behind it, and that is the ticket"* — and a processor cannot tell the difference between a
feature that is broken and one that was never wired.

Three things come off.

### 1. `UploadLinkPanel` and `InboundMessagesPanel`

Both mounted in `app/(protected)/loan-files/[id]/communication/page.tsx`.

**Flag out, do not delete.** LP-815 and LP-807 are written and tested and return in the phase that
brings sending and receiving back. Deleting them buys nothing and costs the review that already
happened.

### 2. `PartyRequestButton` and most of `PartyRequestDialog`

The button goes. But **it was the only place a missing address could be added**, and LP-820 measured
the problem: of 166 document types, **13 across title, agent, CPA, insurer and employer had no
address anywhere in the schema.** The blocker was never "no way to compose" — it was "nobody to send
to".

So the address form is **lifted, not deleted**.

## The address moves to where it blocks something

A party draft with no address is **still created** — refusing would lose the record that the
document was asked for — and appears in the list marked *cannot be sent yet*. The draft itself
carries the form:

> **To** — No address on file for the title company
> *Who are they, and where do we write?*
> Name: `Acme Title` · Email: `closings@acmetitle.com` · `[Save address]`
> *Saved to the file — used for every future message to this party.*

This is the improvement hidden inside removing the button: **the address is asked of the person who
knows it, at the moment it blocks them**, instead of in a panel nobody visits. `add_party_address`
and its form both already exist inside `party-request-dialog`; this lifts them out and drops the
rest.

## Also gone, and worth saying out loud

- **No reminders.** LP-814's clock does not start. Marking a draft sent stamps `requested_at` and
  nothing else runs off it in this version.
- **No `delivered` / `failed`.** They remain valid enum values with no code path that can reach
  them. The furthest the UI goes is `Marked sent by Priya`.
- **No "Send".** Covered in LP-855; repeated here because the page is where the temptation lives.

## What it must not break

- LP-835's party drafts still build, still join the list, still open in the same modal. **Only the
  way in changes** — from a standalone dialog to the request flow plus an inline form.
- `add_party_address` keeps its endpoint and its semantics. The saved address is still a fact about
  the file, used for every future message to that party.
- Flagged-out panels stay compiled and their tests stay green. A flag that rots is a deletion with
  extra steps.

## Acceptance

1. The Communication page shows exactly two buttons: **Request documents** and **Compose**.
2. Requesting a title document with no address on file creates a draft, lists it as *cannot be sent
   yet*, and the draft shows the address form.
3. Saving the address makes the draft sendable without re-requesting the document.
4. `UploadLinkPanel` and `InboundMessagesPanel` are unreachable with the flag off and render
   unchanged with it on; their tests still pass.
5. The upload link is not mentioned anywhere in a generated body while the flag is off.
