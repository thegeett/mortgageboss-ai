# Amendments

Changes to the spec, tickets or assets made *after* implementation started.
Read this alongside `TICKETS.md` — where the two disagree, this file wins.

---

## 2026-08-29 · from the LP-UI-001 review

Three findings were raised on `docs/tickets/LP-UI-001.md`. All three were checked
independently and all three were correct. Two were defects in the assets, and the
assets have been corrected; the third becomes extra acceptance criteria.

### A1 — `fontWeight` was in the wrong place. Fixed in the asset.

**The finding was right.** `fontWeight` sat under `theme.extend`, and Tailwind
*merges* `extend` with the default theme rather than replacing it, so `bold: 700`
survived and `font-bold` still resolved. The comment in the config claiming "700
does not exist in this system" was false.

`assets/tailwind.config.ts` now declares `fontWeight` at **`theme` level**, which
replaces the scale. Verified by compiling a probe through the Tailwind CLI:
`font-bold` emits nothing; `font-normal`, `font-medium` and `font-semibold` emit
400 / 500 / 600. `frontend/tailwind.config.ts` has been updated to match.

**Consequence, and it needs handling in the same breath:** the 12 existing
`font-bold` call sites now resolve to *nothing* and silently inherit their weight.
That is worse than 700 — text meant to be emphasised quietly stops being
emphasised. **This is now part of LP-UI-002** (see below).

The 12 sites are all page or section headings:

```
app/(protected)/admin/lenders/[id]/page.tsx    app/(protected)/dashboard/page.tsx
app/(protected)/admin/lenders/page.tsx         app/(protected)/loan-files/new/page.tsx
app/(protected)/admin/page.tsx                 app/(protected)/loan-files/page.tsx
app/(protected)/admin/validation/page.tsx      app/(auth)/login/page.tsx
app/(protected)/dev/extraction-bench/page.tsx (x2)   app/page.tsx
components/file/file-header.tsx
```

No other weight class is affected — the codebase uses only `font-normal` (13),
`font-medium` (155), `font-semibold` (105) and `font-bold` (12).

### A2 — `--muted-foreground` failed on two of its own surfaces. Fixed in the asset.

**The finding was right, and the arithmetic was right.** Light
`--muted-foreground` was checked against `background` and `card` only. Against the
other two surfaces it sits on it fell short:

| ground | at 44.3% | at 41.0% |
|---|---|---|
| `background` | 4.56 | **5.18** |
| `card` | 4.69 | **5.33** |
| `muted` | 4.28 ✗ | **4.87** |
| `accent` | 4.05 ✗ | **4.61** |

This does not bite today (two `bg-muted` usages, none paired), but the LP-UI-004
codemod maps `bg-gray-50/100 → bg-muted` and `text-gray-300/400/500 →
text-muted-foreground`, and **24 elements currently carry both** — every one would
have landed on 4.28:1.

Light `--muted-foreground` is now **`168.0 4.4% 41.0%`** (`#646D6B`), which clears
4.5:1 on all four grounds with margin. The finding proposed 41.5%; 41.0% was taken
instead because 41.5% reaches only 4.53 on `accent` and hex rounding could push
that under. Dark was already clear at 4.95:1 on its worst ground and is unchanged.

Both `assets/globals.css` and `frontend/app/globals.css` have been updated.

### A3 — Two colour literals the codemod cannot see. Becomes acceptance criteria.

**The finding was right.** `app/page.tsx:143` and `app/(auth)/login/page.tsx:18`
both carry the old Tailwind blue as an arbitrary value:

```
bg-[radial-gradient(circle_at_top,_hsl(217_91%_60%_/_0.08),_transparent_55%)]
```

The codemod only matches `{prop}-gray-{shade}`, so `rg "gray-[0-9]"` comes back
clean while these survive. `LP-UI-004`'s acceptance criteria are extended below.

---

## Ticket changes

### LP-UI-002 — now "Make the config's promises true"

Was: define the missing `danger` colour. The `danger` alias already ships inside
`assets/tailwind.config.ts`, so that half is done. The ticket now also carries the
`fontWeight` consequence from A1.

**Additional scope**

- Replace all 12 `font-bold` occurrences with `font-semibold`. Mechanical; the
  sizes on those headings get adjusted later by their own screen tickets.
- Verify `font-bold` emits nothing: compile a probe through the Tailwind CLI, or
  `rg "font-bold" app components lib` returning nothing is sufficient.

**Additional acceptance**

- [ ] `rg "font-bold" app components lib` returns nothing
- [ ] No heading silently loses weight — check the dashboard and file headers in
      the browser, not just the diff

### LP-UI-004 — extra acceptance criteria

The codemod's own report is not sufficient proof that the old palette is gone.

- [ ] `rg "gray-[0-9]" app components lib` returns nothing (as before)
- [ ] `rg "217 91%|217_91%" app components lib` returns nothing — the two
      arbitrary-value gradients in A3 are replaced with `hsl(var(--primary) / 0.08)`
- [ ] `rg "#[0-9a-fA-F]{3,8}\b" app components lib` returns nothing outside
      comments — no hex literal re-entered

### LP-UI-011 — also decide the root route

`app/page.tsx` is a 199-line developer health/splash page (backend health check,
dependency rows). It is not a processor screen and was deliberately not designed.
It should not survive as-is.

**Additional scope**

- Decide the root route: redirect `/` to `/dashboard` (authenticated) or `/login`,
  and either delete the health page or move it under `/dev` beside
  `extraction-bench`, which is where developer-only surfaces already live.
- Record the choice as an ADR.

---

---

## 2026-08-29 (later) · from the LP-UI-002 review

### A4 — the entire dark theme was being purged from the build. Fixed in the asset.

**The finding was right, and it is the most serious defect in the assets so far.**
Reproduced independently: compiling `globals.css` against the real content globs
emits `:root` and **no `.dark` rule at all**. Add one file containing the bare
token `dark` and the block reappears. Tailwind v3 tree-shakes custom CSS written
inside `@layer base` against the content globs, and nothing in `app/`,
`components/` or `lib/` yields that token — the one file containing the letters is
`rule-findings-tabs.tsx:183`, inside the word "darker" in a comment, which does not
tokenise to `dark`.

So dark mode shipped as nothing, and LP-UI-001's dark checkbox passed only because
verifying it meant adding `className="dark"` to `layout.tsx` — which put the token
into a scanned file and supplied the very condition being tested. That is a sharp
observation and the right lesson: **a verification that changes the thing it
measures is not a verification.**

`safelist: ["dark"]` is now in `assets/tailwind.config.ts` and
`frontend/tailwind.config.ts`, with a comment explaining why it must stay. Verified
after: `.dark` emits against the unmodified content globs. This matters most for
LP-UI-011's theme toggle, which would naturally set the class from a variable
(`classList.add(theme)`) and would otherwise silently kill the theme again.

### The `danger` normalisation stays deferred — agreed

Leaving the twenty call sites spelled `danger` rather than renaming to
`destructive` is the right call: the alias makes them correct, and mechanical churn
does not belong in the same commit as a behaviour fix. `TICKETS.md` marks it
optional and it stays optional.

---

## 2026-08-29 · LP-UI-029 answered — Epic E is unblocked, with a caveat

**There are no bounding boxes, and the model cannot produce one.** Verified
independently: zero geometry anywhere in `backend/app` — no `bbox`, no rect, no
coordinates. Documents reach Claude as native base64 `document` blocks, so there is
no rasterisation and no OCR stage that could have computed page geometry. The
coordinate is not being dropped somewhere; it is never computed.

**Snippet matching is viable, and the numbers are measured rather than assumed.**
Against staging: of 1,456 fields carrying a non-null value, **1,443 (99.1%) carry
both `page` and `snippet`**, and they are populated together — never one without
the other. The 13 without are fields the model reported as absent, which is exactly
where an anchor should be missing.

**One correction to the ticket's own reasoning, and it helps.** It described
`pdf_utils.py` as dev-only. The *text-layer extraction* function is; the module is
not — `cap_pdf_pages` and `pdf_page_count` are imported by `classification.py`,
`generic_analyzer.py`, `chunked.py` and `bank_statement.py`. PyMuPDF is therefore
already on the production path, so `page.search_for()` is a smaller lift than the
ticket implies: no new dependency and no new stage, just a service.

### What is still unmeasured, and should be before Epic E is scheduled

1. What share of stored documents have a usable text layer (`search_for` finds
   nothing on a scan). `pdf_utils.has_text` already computes the signal.
2. Whether the snippet matches the text layer verbatim — ligatures, soft hyphens,
   column order and whitespace runs all break an exact search.

### Decision, and what it costs the design

The recommendation is right: **do not block Epic E on true coordinates.** Ship
snippet matching, treat `bbox` as derived and optional, and make it **absent rather
than approximate** when the search fails.

That has a design consequence I own, not the implementer: **the Review screen in
`ledger-screens.html` promises a rectangle on every field, and it cannot.** The
mockup needs a designed *"page known, spot unknown"* field state — page number and
quoted snippet, no box, and no implication that one is missing by error. That state
is needed regardless, since 0.9% of valued fields have no page either.

**Owed by the design side, before LP-UI-030 starts:** ~~add that state to the
Review screen and to the Foundations state vocabulary.~~ **Done, 2026-08-29 19:2x.**

The Review screen now carries a twelfth field, *Employer match*, in the
**page known, spot not located** state. Hovering it lights no box; instead the page
takes a dashed outline and a caption reading *"page 2 · no text layer to search"*.
The field itself shows the value normally, a dashed-pin provenance line
(`p.2 · page known, spot not located`) and the verbatim snippet quoted in serif
italic — the document speaking, which is the one place that face is used.

Deliberately **not** styled as a problem: no amber, no warning glyph, no left rail.
On a scanned document this is every field, and a screen that flags the normal case
as a fault teaches processors to ignore the flag. The header strip counts it
honestly — "12 fields · 4 need a look · 1 not located".

Foundations gains a **Provenance** row, kept separate from the status vocabulary,
because a field can be perfectly verified and still have no box:

| | meaning |
|---|---|
| solid pin | Located — page and spot |
| dashed pin | Page known, spot not located |
| violet spark | Inferred, not read |
| dashed circle | Not on this document |

LP-UI-030 now has a mockup for the case that will occur on every scan.

Epic E stays scheduled where it is on the assumption that snippet matching is the
approach. If the alternative — a real OCR/geometry stage — is preferred, that is a
new backend epic and Epic E moves.

---

---

## 2026-08-29 (later still) · A5 — the codemod's expected numbers were stale

**Re-measured against HEAD before LP-UI-004 runs, so the ticket is not checked
against a phantom.** The current dry run reports **803 replacements across 70
files, 3 unmapped** — not the 811 the ticket and the script header claimed.

Both figures are now corrected in `TICKETS.md` and in the script's own comments.

**Why it moved is not established, and I am not going to invent a cause.** What
*is* established: `gray-N` occurrences in `frontend/` `.ts`/`.tsx` are **808 at
both the docs commit and HEAD** — identical — and no `.tsx` file lost a grey class
between them. 803 mapped + 3 unmapped = 806, so two occurrences sit in a context
the pattern does not match at all, which is expected and harmless. The earlier 811
exceeded the total occurrence count, so it was wrong when it was written; the
measurement taken now, against the tree the codemod will actually run on, is the
one to trust.

**For LP-UI-004:** expect 803 / 70 / 3. A drift from *that* is worth reading. And
the acceptance criteria stand as written — the greps are the real proof, not the
script's own report, which is exactly why they are there.

---

---

## 2026-08-29 (idle tick) · A6 — pre-checked every pairing LP-UI-004 will create

Nothing was moving, so the codemod's remaining contrast risk was measured ahead of
the ticket rather than after it. Every `className` in the codebase was scanned for
a background and a text colour that the mapping will convert together.

**Three pairings will exist, and all three clear 4.5:1 in both themes:**

| pairing | elements | light | dark |
|---|---|---|---|
| `bg-muted` + `text-muted-foreground` | 14 (10 files) | 4.87 | 5.38 |
| `bg-muted` + `text-foreground-2` | 9 (8 files) | 7.50 | 8.71 |
| `bg-muted` + `text-foreground` | 2 (1 file) | 16.70 | 14.15 |

So A2's correction did its job: the 14 elements that would have landed on 4.28:1
now sit at 4.87:1. LP-UI-004 should not produce a single new contrast failure.

**One latent trap, closed in the SPEC rather than in the palette.**
`bg-border` + `text-muted-foreground` is **4.27:1** in light. It does not occur —
nothing pairs them — so there is nothing to fix, but the mapping sends
`bg-gray-200/300` to `bg-border`, and the next person to put muted text on one of
those surfaces would land under the floor with no warning. `SPEC.md` now states
that `bg-border` is for rules, dividers, dots and troughs, never a text surface,
and points at `bg-muted` as the filled alternative.

---

## Standing note

The design assets are **not** infallible. LP-UI-001 found two real defects in them
by verifying rather than trusting, which is exactly right. Keep doing that: if a
ticket's premise does not survive contact with the code, say so on the ticket
rather than working around it, and the asset gets corrected here.
