# LP-858 — Draft panel: the UI contract

**This file is the specification. Build against it literally.**
`lp858-draft-panel-screens.html` beside it is the same thing rendered — open it in a browser to see
the layout. It is for people; **this file is for whoever writes the code**, and where the two
disagree, this one wins.

- **Ticket:** [`../tickets/LP-858.md`](../tickets/LP-858.md)
- **Decision doc:** `comm-v1-draft-only-spec.md` (project) — §6 buttons, §8 mail client. **Note §2 of
  that doc is stale:** it says one open draft per party enforced server-side, and LP-832 dropped
  `uq_communications_open_draft`. Many open drafts is the ordinary state.
- **Tokens:** `frontend/app/globals.css`. **Not** the palette in `CLAUDE.md`, which is out of date —
  the primary is `--primary: 187.9 67.9% 22.0%` (deep teal), not blue.

---

## 1. Why this file exists

The previous round of this work was specified in prose and built as something else. Three distinct
things went wrong, and each one is a rule below:

| What happened | Why prose allowed it | The rule now |
|---|---|---|
| `[Delete]` was specified, a **comment** describing the button row shipped at `message-dialog.tsx:629`, the button never did | prose can be satisfied by restating it | **§6 — every requirement has a check you can run** |
| Everything became a Radix `Dialog`; the spec never said which container | an unstated choice becomes the model's default | **§3 — the component is named, and the wrong one is named too** |
| Spec said "one open draft per party"; the index had been dropped | the spec lived outside the repo and drifted | **this file is in the repo** and changes in the same PR as the code |

---

## 2. Layout

```
┌───────────────────────────┬─────────────────────────────────────┐
│ LEFT — list               │ RIGHT — the selected draft     [✕]  │
│  fixed 300px              │ fills remaining width               │
│                           │                                     │
│  header: "Drafts &        │  header: To … / subject line        │
│  messages" + Compose      │  toolbar: the LP-854 editor         │
│  rows: one per draft      │  body:   the rich editor            │
│         and sent message  │  footer: the button row (§4)        │
└───────────────────────────┴─────────────────────────────────────┘
```

- **The split is the landing state, not something a click produces.** The list does not open
  full-width and collapse when a row is selected — that is a layout jump on every click, and this
  list is per loan file, so it holds one to three rows, not an inbox's worth. Selecting a row swaps
  the right pane's content and moves nothing.
- **300px on the left**, wide enough for party, subject preview, document count and time. A 238px
  rail that can only hold a name and a timestamp is what makes a full-width list tempting; the fix
  is the width, not the pattern.
- **Zero drafts is the exception: there is no split.** Do not render an empty rail beside an empty
  pane. One full-width empty state (§2.1 rule 4).
- Nothing in this tab opens in a modal **except** the mail-client question (§5) and the delete
  confirm (§7), which overlay the right pane and leave it visible behind them.
- Below ~720px the two panes stack: list first, draft under it.

---

## 2.1 What is selected on load — DECIDED 2026-09-13

**Auto-select the newest OPEN DRAFT.** The right pane is never a dead panel on a file that has work
outstanding.

Safe to do, and checked rather than assumed: opening a draft has **no side effect**. Autosave is
guarded by `dirtyRef` (`message-dialog.tsx:328`) and only marks dirty when the html differs from what
the pane opened with (`:355`), so selecting a draft cannot write to it, cannot set the edited flag,
and cannot stamp a read timestamp.

Selection rules, in order:

1. **A draft named in the URL wins** (`?draft=<id>`). Selection is URL-driven so a toast — *"Draft to
   the borrower created"* — can link straight to it, and a reload keeps the same draft open.
2. Otherwise **the newest open draft**.
3. **Never auto-select a sent message.** A read-only record is not what the processor came for, and
   when receiving returns it would mark inbound mail read that nobody looked at.
4. **No drafts at all** — the two-pane layout does not render. The tab is **one full-width empty
   state**, centred:

   > **No drafts on this file**
   > Request documents from a finding, or write a message.
   > `[ Request documents ]` `[ Compose ]`

   **Sent messages but no open drafts** is different: the split *does* render, the list shows the
   sent history, and the right pane carries the same empty state inside it. History is worth seeing;
   an empty file is not worth a rail.

5. **Stacked layout (below ~720px): select nothing.** The panes are vertical there, so auto-selecting
   pushes the list off-screen and hides the thing that orients the processor. The list is the screen;
   tapping a row opens the draft.
6. **After deleting the selected draft**, select the next newest open draft, or fall to the empty
   state. Never leave the pane showing a deleted row.

7. **A CLOSED PANE IS NOT AN EMPTY FILE — ADDED 2026-09-13, after LP-859.** Closing with ✕ sets a
   closed state and auto-selection must not undo it (or the pane cannot be dismissed). But the pane
   must not then borrow rule 4's words: a screen reading *"No drafts on this file"* beside a rail
   listing four is a contradiction, and the wrong half is the one in larger type. Three states:

   | Condition | Right pane |
   |---|---|
   | no entries at all | full-width **"No drafts on this file"** |
   | no open drafts, but sent history | in-pane **"No drafts on this file"** — true, keep it |
   | **open drafts exist, pane closed** | **"No draft selected"** / *"Pick one from the list, or start a new message."* |

   Do not re-select on close. That trades a false sentence for a pane nobody can dismiss.

## 2.2 The row itself — ADDED 2026-09-13, after LP-859

§2 said the rail is 300px and named what a row must hold. **It did not say the row stacks**, and the
row it inherited was a four-column horizontal layout built for a full-width list. Three of those four
columns could not shrink, so at 300px the only flexible one collapsed to one word per line and the
status line ran outside the rail. An unstated layout is the same defect class as an unstated
component, and §3 is the rule for components. This is the rule for the row.

```
┌─ 300px ───────────────────────────────┐
│ ✎ BORROWER              1 day ago     │  line 1 — party, then time
│ Draft · edited                        │  line 2 — the state, as a word
│ 3 documents · Insurance, Licence, …   │  line 3 — what is inside, truncated
└───────────────────────────────────────┘
```

- **Three lines at most.** A row taller than three lines is a row the list cannot be scanned through.
- **Nothing may be `whitespace-nowrap` and `shrink-0` at the same time.** That pair is what put text
  outside the rail; either the text wraps or the box gives way.
- Attribution (*"Marked sent by Geet Thaker"*) belongs on line 2, which has the width for it. It is
  the longest string this screen can produce and it is what to test against.
- The party cell may stay fixed at `5.6rem` — it is 90px of a line that is now 300px long.

## 3. Components — named, including the wrong one

| Surface | Build with | **Do not use** |
|---|---|---|
| Right pane | inline layout in `communication/page.tsx`, or `components/ui/sheet.tsx` if a slide-over is wanted on narrow widths | `components/ui/dialog.tsx` |
| Mail-client question | `components/ui/dialog.tsx` — it is a genuine interruption | — |
| Delete confirm | `components/ui/dialog.tsx` | — |
| Rich editor | the existing `communication/message-editor.tsx` | a second editor instance; a second TipTap mount |

`compose-draft-dialog.tsx` **is deleted**, not adapted. Compose is the right pane in create mode.
`message-dialog.tsx` becomes the right pane; it stops being a `Dialog`.

---

## 4. The button row — exact, in this order

```
[ Copy & open <client> ]  [ Copy message ]  [ Mark as sent ]   ……spacer……   [ Delete ]
      primary                secondary          secondary                     quiet, danger text
```

- `<client>` is the saved preference: `Gmail` · `Outlook` · `mail app`. **Until one is saved the
  label reads `Copy & open mail app`** — never a blank, never "Gmail" by assumption.
- **There is no Send button.** Not disabled, not "coming soon". `mail_transport` has no provider.
- **There is no ✦ polish button when `email_draft_enabled` is false** — hidden, not rendered
  refusing. The page's own principle, `communication/page.tsx:20-24`: *"a processor cannot tell a
  feature that is broken from one that was never wired."*

---

## 5. The mail-client question

**Trigger: pressing `Copy & open …`, and only that.** Never on opening a draft, never on
`Copy message`, never on `Mark as sent`, never on mount.

Today it is wrong at `message-dialog.tsx:376` — `open={open && !needsClient}` hides the draft while
the picker shows, on the first editable draft of a session. Delete that coupling.

- The draft stays visible behind the dialog.
- The suggested client is **pre-selected and says why** ("Suggested — you sign in with a Google
  Workspace address"). Never applied silently.
- "Whatever this computer opens" is always an option and is the skip answer.
- **Answering completes the original action in the same gesture.** The processor does not press
  `Copy & open` a second time.

---

## 6. State table — what is on screen when

| Condition | Left row reads | Right pane |
|---|---|---|
| generated draft, untouched | `Draft · today 09:14` | body + full button row |
| processor edited it (`body_edited`) | `Draft · edited · today 09:14` | same; delete now confirms (§7) |
| party has no address | `Draft · cannot be sent yet` + `no address` chip | inline name/email/Save block above the body; `Copy & open` disabled, `Copy message` **enabled** |
| new compose, nothing typed | `New message` / `Nothing written yet` | empty To, Subject, body |
| marked sent | `Marked sent by Priya · Tue 16:41` | read-only |
| **pane closed, drafts still in the list** | unchanged | **`No draft selected`** — never rule 4's words (§2.1 rule 7) |

---

## 7. Delete — DECIDED 2026-09-13

**No route exists today.** `api/communications.py` has `GET /draft`, `POST /compose`,
`PUT /draft/{id}/body`, `POST /draft/{id}/polish`, `POST /draft/{id}/send` — and nothing else. Add
`DELETE /draft/{draft_id}`.

Two different deletes, and they are not the same operation:

| Case | What happens |
|---|---|
| **A draft the processor deletes** (any draft, any state) | **Soft delete** — set `deleted_at`. The row stays in the database. |
| **A composed draft closed without a single modification** | **Hard delete** — remove the row. Nothing was ever written, so there is nothing to keep. |

### It does NOT un-request. Decided.

> *"No keep it simple, do not un-request."*

Deleting a draft **leaves needs items and findings exactly as they are.** Do not call
`_clear_finding_markers`, do not reopen needs, do not clear `details.docs_requested`.

**The known consequence, recorded so nobody treats it as a bug later:** the originating finding
keeps rendering its request button as **"Requested" and disabled** (`finding-card.tsx` reads
`Boolean(details.docs_requested)`). The processor is not blocked — the **Request documents** catalog
dialog still adds the document — but that one button on that one finding stays greyed.

Note this residue is smaller than it first appears: `request_needs_item` still has no caller, so
`requested_at` is NULL and the needs items are still `PENDING` on an unsent draft. There is no clock
running and nothing to unwind. **The only stale thing is the finding's button.**

### Confirms

- **No confirm** when `body_edited` is false. Toast with an **Undo**.
- **Confirm** when `body_edited` is true, quoting the processor's own first edited line back at them
  — the same pattern LP-851 uses for the append warning.
- The hard-delete case (a compose draft closed untouched) is **silent**. No toast, no undo, nothing
  to undo.

## 8. The empty compose draft — DECIDED 2026-09-13

**The row is created when Compose is pressed.** It appears in the left list immediately, reading
`New message` / `Nothing written yet`.

On closing the right pane:

- **No modification at all** — To, Subject and body all still empty → **hard delete the row.** Not
  soft, not `deleted_at`: it never held anything.
- **Any modification** — even a recipient typed and nothing else → the draft stays, as an ordinary
  draft in the list.

"Modification" means any of the three fields differs from what the pane opened with. A processor who
typed a recipient and stopped has done work; do not destroy it.

**The abandoned case is accepted.** If the browser or tab closes rather than the ✕ being pressed, the
empty row survives in the list. That is the cost of creating on click, it was chosen knowingly, and
the processor clears it with Delete. Do not build a sweep for it.

## 9. Acceptance — every line here is a command, not an opinion

A reviewer runs these. A ticket that satisfies the prose above but fails one of these is not done.

```bash
# §3 — the draft is not a modal any more, and compose is gone
rg -n "Dialog|DialogContent" frontend/components/file/communication/message-dialog.tsx   # → mail-client + delete confirm ONLY
test ! -f frontend/components/file/communication/compose-draft-dialog.tsx                # → must not exist

# §4 — no Send, and polish is absent rather than refusing
rg -in "\bsend\b" frontend/components/file/communication/ | rg -v "Mark as sent|sent by|marked sent"   # → nothing
rg -n "email_draft_enabled|polishAvailable" frontend/                                    # → a render guard, not a refusal string
rg -rn "not available on this environment" frontend/                                     # → nothing

# §5 — the picker is not coupled to opening a draft
# NOTE: grepping for the old `open={open && !needsClient}` is USELESS — the fix's own comments
# quote that string, so it matches forever. Check the live wiring instead:
rg -n "open=\{pickerOpen\}" frontend/components/file/communication/message-dialog.tsx    # → exactly 1
# Counting hits does not work either — JSX {/* */} comment bodies match any filter you write.
# Assert the two LIVE lines by shape instead:
rg -n "const needsClient = " frontend/components/file/communication/message-dialog.tsx    # → 1, a capability test only
rg -n "if \(client === null && needsClient\)" frontend/components/file/communication/message-dialog.tsx  # → 1, inside the copy-and-open handler
# Anything else that mentions needsClient must be prose. Read it; do not count it.

# §7 — delete exists, and does NOT touch finding state
rg -n '@router.delete' backend/app/api/communications.py                                 # → one route
rg -n "_clear_finding_markers" backend/app/services/email_draft.py                       # → NOTHING. deleting must not call it
```

**Tests that must exist and be named for the behaviour, not the mechanism:**

- `test_opening_a_draft_does_not_ask_which_mail_client`
- `test_copy_and_open_asks_once_then_completes_the_action`
- `test_deleting_a_draft_leaves_its_needs_and_finding_markers_untouched`
- `test_deleting_a_draft_sets_deleted_at_and_keeps_the_row`
- `test_deleting_an_edited_draft_confirms_and_quotes_the_edit`
- `test_closing_an_untouched_compose_draft_removes_the_row_entirely`
- `test_a_compose_draft_with_only_a_recipient_survives_close`
- `test_the_newest_open_draft_is_selected_on_load`
- `test_a_file_with_only_sent_messages_selects_nothing_and_shows_the_empty_state`
- `test_a_file_with_no_drafts_renders_one_full_width_empty_state_and_no_list_rail`
- `test_a_draft_id_in_the_url_beats_the_default_selection`

---

## 10. Literal strings — use these, do not invent

```
"Drafts & messages"          left pane header
"+ Compose"                  left pane action
"New message"                row title, composed draft with no recipient
"Nothing written yet"        row subtitle, same
"Draft · cannot be sent yet" row subtitle, party with no address
"no address"                 chip on that row
"Marked sent by {name} · {when}"
"Copy & open mail app"       button, no client saved
"Copy & open {Gmail|Outlook}" button, client saved
"Copy message" / "Mark as sent" / "Delete"
"Paste into the message — ⌘V."          after Copy & open succeeds
"No address on file for the {party}"     heading of the inline address block
"Who are they, and where do we write?"  the line under it
"Which mail app should this open?"      picker title
"Asked once. You can change it in preferences."
"Delete this draft?" / "You edited it. Your first change was:"
"No drafts on this file"                 pane/tab empty state — only when there are none
"No draft selected"                      pane closed while drafts remain in the list
"Pick one from the list, or start a new message."   the line under it
```
