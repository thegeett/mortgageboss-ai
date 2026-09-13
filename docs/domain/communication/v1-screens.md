# Appendix A — the screens, in text

The visual mockups live outside the repo. **This appendix is the authoritative description**;
build from it. Copy shown in quotes is literal and should ship as written unless a ticket says
otherwise.

All of it obeys the Ledger: petrol `#12545E`, IBM Plex Sans/Mono/Serif, hairlines not cards, 28px
rows, status is colour **and** glyph **and** word, AI violet marks provenance and never status,
Plex Serif italic is reserved for verbatim quotation of a document.

## Screen 1 — the list · LP-852, LP-857

Page header row, right-aligned, **exactly two buttons**: `Compose` (outline) and
`Request documents` (primary). No "Write to another party".

Below it, one list, newest first, **no groups and no tabs**. Each row is a three-column grid —
`auto 1fr auto`, 28px minimum height, hairline between rows:

| col | content |
|---|---|
| 1 | Party, 5.6rem fixed, uppercase 11px, muted — `Borrower` (petrol) / `Title co.` / `Lender` |
| 2 | Subject, then the document names in muted text. A petrol dot precedes it when the draft was created since this processor last opened the page |
| 3 | Status, mono, muted — `Draft · edited · 2m` / `Sent by Priya · Mon 16:41` |

Empty state, centred, muted: *"Nothing has been written on this file."* and beneath it
*"Request documents to start a draft, or compose one yourself."*

**The party is a column, never a heading.** A heading is a region that can be scrolled past, which
is the reported defect.

## Screen 2 — the draft · LP-853, LP-854, LP-855

Modal. Top to bottom:

1. **To** and **Subject**, label/value rows, 5rem label column, hairline under each.
2. **The toolbar**, one row, wraps at narrow widths, sunk background, rounded top only:
   `↶ ↷ | B I U | bullets ordered outdent indent | quote link | clear` — then flex spacer — then
   `✦ polish` in violet with a violet border.
3. **The editor**, joined to the toolbar (no top border, rounded bottom). Paragraphs 0.6rem apart,
   bullets indented 1.1rem, nested detail bullets smaller and muted.
4. **What it asks for · N documents** — a bordered block, petrol uppercase heading, document names
   as small muted chips. **Read-only here.** Documents join a draft through the request flow.
5. **The button bar**: `Copy & open Gmail` (primary, label carries the chosen client) ·
   `Copy message` · `Mark as sent` — flex spacer — `Delete` (ghost, far right).

No Send button, not even disabled.

## Screen 3 — adding to an open draft · LP-851

Dialog, max 32rem.

> **There is already an open draft to the borrower**
>
> Created Tue 14:02, asking for:
>
> `Bank statement — March` `Pay stub`
>
> Add **Homeowner's insurance declaration** to it — or, if you have already sent that draft from
> your mail client, mark it sent and start a new one.

Actions, right-aligned, hairline above:
`Cancel` (ghost) · `I've sent it — mark sent, start new` · `Add to the open draft` (primary).

**Three buttons. There is no "start a second draft".**

## Screen 4 — one request, two parties · LP-851, LP-852

Same dialog, max 34rem, titled **"This request goes to two people"**, with one bordered block per
party instead of a single body.

Block with an open draft — petrol uppercase heading *"Borrower · a draft is already open"*, the
documents being added as chips prefixed `+`, a muted line *"Open since Tue 14:02, asking for 2
documents."*, then its own two buttons: `Mark sent, start new` and `Add to it` (primary).

Block with nothing open — *"Title company · a new draft"*, chips, and a muted line
*"Nothing open — this creates a draft to closings@acmetitle.com."* **No buttons.** It needs no
decision but the processor must leave knowing it exists.

Footer actions: `Cancel` · `Do both` (primary).

## Screen 5 — the draft has the processor's words in it · LP-851, LP-853

Screen 3 plus one block above the actions, amber left border on amber tint:

> **You have edited this draft.** Adding a document rewrites the message from the template, and your
> changes — including *"March statement only, not February"* — will be lost. Copy anything you want
> to keep first.

The quoted fragment is **the processor's own first edited line**, pulled from the draft. Primary
becomes `Add anyway`.

## Screen 6 — "Request all", folded in · LP-851

The existing confirm keeps its title (*"Request 5 documents?"*) and its document list. When a draft
is open it gains the Screen 4 party blocks between the list and the actions, and the actions become
`Cancel` · `Mark sent, start new` · `Add to the open draft`.

**One dialog. Never two in sequence** — a processor who has just confirmed five documents and is
then asked a second question clicks the primary without reading it.

## Screen 7 — "Request documents" · unchanged

Shown only to confirm nothing changes: search field, the file's outstanding needs ordered first,
`already requested` marked in amber at selection time, `N selected` and `Generate email`. After
Generate, the LP-850 rule applies and Screen 3, 4 or 5 follows.

## Screen 8 — compose, and the AI button · LP-856

Same modal as Screen 2 with an empty "What it asks for" block and an editable **To**.

After `✦ polish`, the proposal replaces the editor in place under a violet header reading
**"After ✦ polish — not saved yet"**, with its own two actions: `Undo — put mine back` (ghost, left)
and `Keep this` (primary, right). The original is held until one is chosen.

## Screen 9 — a party with nowhere to send · LP-857

The draft opens normally but its header is amber: *"Draft to the title company · cannot be sent
yet"*, and **To** reads, in amber, *"No address on file for the title company"*.

In place of the button bar: a prompt line *"Who are they, and where do we write?"*, a **Name** field
and an **Email** field, then a bar with the muted note *"Saved to the file — used for every future
message to this party."* and `Save address` (primary).

The draft is still created and still appears in the list. Refusing to create it would lose the
record that the document was asked for.

## Screen 10 — which mail client · LP-855, retriggered by LP-858 §1

Dialog, shown once — **on pressing `Copy & open …`, not on opening a draft.**

LP-858 moved the trigger. It used to open on the first editable draft of a session, which asked a
processor which mail client they use about a message they had not read yet; it was reported from use
in those words. Answering completes the original action in the same gesture — there is no second
press. `Copy message`, `Mark as sent` and simply reading a draft never raise it.

> **Which mail app should this open?**
>
> Asked once. You can change it in preferences.

Three bordered option blocks; the seeded one has a petrol border and a filled radio:

- **Gmail** — *"Opens mail.google.com — suggested, because you sign in as priya@…"*
- **Outlook on the web** — *"Work or personal account"*
- **Whatever this computer opens** — *"Apple Mail, desktop Outlook, Thunderbird — the safe answer if
  you're unsure"*

Actions: `Not now` (ghost, selects `mailto:`) · `Use Gmail` (primary, label follows the selection).

The seed **moves a radio button and says why**. It never decides.
