# Communication v1 — draft only

Decision document. Read from `phase4-with-ui`. Updated 2026-09-13 with all decisions resolved.
Readable versions: artifacts **"Draft Only"** (rationale) and **"Draft Only Screens"** (every screen).

**Status: decided. Ready to ticket — with one trade still open, see §7.**

---

## 1. The fence

One version that does one thing: **it writes drafts**. Nothing sends, nothing arrives,
nothing reminds. Delivery is a person with their own mail client, and every screen says so.

**In** — creating a draft from a request; appending to an open draft; a free draft the processor
writes; AI polish on demand; rich text and a copy that keeps the formatting; opening the
processor's mail client with To/Subject prefilled; Mark as sent, attributed; per document, what is
asked and where to get it.

**Out — next phase** — sending from the app; receiving, inbound parsing, attachments; replies and
threading; the secure upload link; reminders / chasing (LP-814); `delivered` / `failed` status;
anything claiming to know the borrower received it.

Two panels come off the page: `UploadLinkPanel` and `InboundMessagesPanel`, both mounted in
`app/(protected)/loan-files/[id]/communication/page.tsx`. **Hide behind a flag, do not delete.**

---

## 2. The rule — DECIDED

> When a document is requested: **if a draft is already open for the party that document belongs to,
> ask. If not, create one and toast it, naming the party.**

- **One open draft per party, enforced server-side.** "Create a second draft" does not exist.
  (Decision: *"No two open draft for same party. Keep it simple."*) This removes the
  four-identical-rows defect by construction rather than by asking the processor to be careful.
- Party comes from `get_guidance(needs_type).responsible_party` — borrower for 113 of 167 types.
- No dialog on the empty case.

**Dialog copy** (screens 3–5 of the screens artifact):

> **There is already an open draft to the borrower**
> Created Tue 14:02, asking for: *Bank statement — March · Pay stub*
> Add **Homeowner's insurance declaration** to it — or, if you have already sent that draft from
> your mail client, mark it sent and start a new one.
> `[Cancel]` `[I've sent it — mark sent, start new]` `[Add to the open draft]` ← primary

"I've sent it", not "Mark as sent": nothing observed a send, and the record afterwards reads
`Marked sent by Priya · Tue 16:41`.

**Multi-party selections:** one dialog, one row per party. A party with nothing open still gets a
row with no buttons — the processor must leave knowing a second draft exists.

---

## 3. Append vs hand edits — DECIDED

`_add_to_party_draft` calls `_regenerate`, which rebuilds the body from the template. Rich text
means processors edit that body, and with the note field gone it is the **only** place their own
words live.

**v1:** a `body_edited` flag, set the first time a saved body differs from the generated one. When
set, the dialog shows a warning block that **quotes the processor's own first edited line back at
them** before offering "Add anyway".

**Later:** split the body into a generated document block and processor-owned framing, and
regenerate only the block. Schema change; belongs with the sending phase.

---

## 4. The three entry points

| Entry point | File | Change |
|---|---|---|
| Individual request on a finding | `verification/rule-finding-actions.tsx` | **The "Anything to add for the borrower?" form is removed.** `Request` runs the rule directly. (Decision: gone in v1.) |
| "Request all N" | `verification/bulk-request-button.tsx` | Keep its confirm; **fold the message into it** as extra blocks. Never two dialogs in sequence. |
| "Request documents" | `communication/compose-request-dialog.tsx` | **Unchanged.** Catalog, needs-first ordering, "already requested" markers all stay. |

---

## 5. Removed: "Write to another party" — and its consequence

Decision: **no "Write to another party" button in v1.** It was the only place a missing address
could be added, and **13 of 167 document types have no address anywhere in the schema**.

So the address moves to where it blocks something: a party draft with no address is **still
created**, appears in the list marked *cannot be sent yet*, and carries an inline
name + email + Save address block in the draft itself. Reuses the existing `add_party_address`
endpoint and the form already inside `party-request-dialog`; the rest of that dialog is deleted.
**Net deletion, and the address is asked of the person who knows it at the moment it matters.**

---

## 6. Buttons on a draft — DECIDED: three and a quiet fourth

`[Copy & open Gmail]` (primary) · `[Copy message]` · `[Mark as sent]` … `[Delete]` (quiet, far side)

1. **Copy & open <client>** is the whole send path in one click — it puts the **rich** body on the
   clipboard *and* opens the compose window with To and Subject filled. Label carries the chosen
   client.
2. **Copy message** stays for anyone doing it their own way.
3. **Mark as sent** is attributed — "Marked sent by Priya · Tue 16:41". Stamps `requested_at`,
   closes the draft. Starts no clock; there are no reminders in this version.
4. **No Send button at all** — not greyed, not "coming soon". `mail_transport` has no provider.

---

## 7. The toolbar — Gmail's, and what it costs

Gmail's compose bar, and the call on each:

| Gmail has | Take | Why |
|---|---|---|
| Undo · Redo | **yes** | Table stakes. TipTap ships history. |
| Font family | **no** | A request in Comic Sans is a real outcome, and fonts don't survive `mailto:`. |
| Text size | *optional* | Harmless, unused in a business letter. |
| Bold · Italic · **Underline** | **yes** | Underline is new. All three survive a paste. |
| Text colour / highlight | **no** | Colour means status in the Ledger. A red sentence is a claim nobody intended. |
| Align | **left only** | Centred body text is a formatting accident. |
| **Numbered list** | **yes** | "Send these three, in this order." |
| Bulleted list | have it | LP-849. |
| **Indent more/less** | **yes** | It builds the nested detail block already in the output. |
| **Quote** | **yes** | Plex Serif italic is already reserved for verbatim quotation. |
| **Link** | **yes** | Most-wanted, not in the schema today. |
| **Remove formatting** | **yes** | The repair tool for pasted-in text. Without it a bad paste is unfixable. |

### The cost — this is the open trade

The stored body is **one plain string**, converted in and out by `emailBodyToHtml` /
`htmlToEmailBody`. LP-849 chose that narrow schema *precisely so the editor could not produce
something the converter drops*. **Underline, links, numbered lists, indent and quote cannot
round-trip through it.** So a Gmail-grade toolbar means **storing HTML instead of a plain string**:

1. **Store HTML, not ProseMirror JSON** — HTML is what the clipboard, a future send provider, and
   anything outside the editor can read.
2. **Resolve placeholders before the HTML exists.** `finalise_draft_body` substitutes into a plain
   string. Run it at generation and convert once, or a placeholder split across `<strong>` tags
   becomes a bug that surfaces on one draft in a hundred.
3. **Sanitise server-side, on the way in.** `email-body.ts` is safe by *construction* today — escape
   everything, then emit its own tags, no passthrough to leave open. Storing author HTML ends that.
   An allowlist replaces it, **in the same ticket**.
4. **Derive plain text, never store it twice.** `mailto:` and the deep links need it. Strip from the
   HTML on demand.

**Open question:** ticket 4 is large and touches templates, placeholders, clipboard, `mailto:`
derivation and the security model at once, and exists only because the toolbar must look like
Gmail's. Keeping **bold, italic, bullets and links** inside the current plain-string schema is a
fraction of the work and covers most of what a document request needs. *Confirm the trade before
ticketing.*

---

## 8. Opening Gmail / Outlook — answered

All four routes exist and take `to`, `subject`, `body`. **Every one takes the body as plain text.**

| Route | URL |
|---|---|
| Gmail | `mail.google.com/mail/?view=cm&fs=1&to=…&su=…&body=…` |
| Outlook — work | `outlook.office.com/mail/deeplink/compose?to=…&subject=…&body=…` |
| Outlook — personal | `outlook.live.com/mail/0/deeplink/compose?to=…&subject=…&body=…` |
| Desktop default | `mailto:…?subject=…&body=…` (plain text per RFC 6068) |

**So the button does both things:** copies the rich body to the clipboard **and** opens the compose
window with To and Subject filled and **the body left empty**, then says *"Paste into the message —
⌘V"*. Filling it with stripped plain text hands the processor a message that looks finished but
isn't. Leaving it empty also sidesteps the URL length ceiling that `mailto_max_chars` exists for.

**Which client?** Nothing in the browser can detect it. It is a **per-user preference**
(`preferences` API already exists — one string), asked once on the first draft:

- Seed the default from their own sign-in domain (`@gmail.com` / Workspace → Gmail;
  `@outlook.com` / M365 → Outlook). **It pre-selects a radio button and says why — never applied
  silently.**
- **"Whatever this computer opens"** (`mailto:`) is the safe answer and the fallback when they skip.
  Until they choose, the button reads *Copy & open mail app*.

---

## 9. Rich text — what already exists (do not re-buy)

- **TipTap shipped in LP-849.** `communication/message-editor.tsx`, `@tiptap/react` 3.31, MIT,
  ProseMirror. **Do not add a second editor.**
- **The clipboard is already right.** `lib/markdown/copy-rich.ts` writes a `ClipboardItem` with
  **`text/html` and `text/plain` together**, `writeText` fallback. That pairing is the requirement —
  HTML alone fails silently in Chromium.
- **The HTML is already mail-client safe.** `lib/markdown/email-body.ts` emits bare `<p>`, `<ul>`,
  nested `<ul>`, `<strong>` — no classes, no stylesheet dependency — which is why it survives
  Outlook desktop's Word rendering engine.

---

## 10. Tickets — eight, in order

1 blocks 2 and 3; 4 blocks everything that renders a body.

1. **The rule and its dialog** — one open draft per party enforced server-side, multi-party rows,
   the `body_edited` flag and its warning. *large*
2. **The three entry points wired to it** — remove the note form, fold the message into "Request
   all", leave the catalog dialog alone. *medium*
3. **Always name the party** — toast and dialog copy everywhere a draft is created. *small*
4. **HTML bodies** — storage change, placeholder resolution moved ahead of conversion, server-side
   sanitiser. **The one with real risk.** *large*
5. **The Gmail-grade toolbar** — underline, numbered list, indent, quote, link, remove formatting,
   undo/redo. On top of 4. *medium*
6. **Copy & open** — the four routes, the client preference, the picker. *medium*
7. **Compose and polish** — the free draft, the AI endpoint, accept/undo. *medium*
8. **Take the next phase off the page** — flag out the two panels; lift the address form out of
   `party-request-dialog` and delete the rest. *small*
