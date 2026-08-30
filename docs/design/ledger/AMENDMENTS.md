# Amendments

Changes to the spec, tickets or assets made *after* implementation started.
Read this alongside `TICKETS.md` — where the two disagree, this file wins.

> **Ordering:** amendments are NOT in file order — successive appends by two
> sessions have left the newest ones at the top and the standing note mid-file.
> Read by amendment NUMBER (A1…A29), not by position. Worth tidying once the
> epic is done; not worth a merge conflict mid-ticket.

Amendments run **A1 upward in order below**, newest last. New ones append at
the END of the file. The standing note is pinned here at the top so it cannot be
stranded mid-file again — it has happened twice.

## Standing note

The design assets are **not** infallible. LP-UI-001 found two real defects in them
by verifying rather than trusting, which is exactly right. Keep doing that: if a
ticket's premise does not survive contact with the code, say so on the ticket
rather than working around it, and the asset gets corrected here.

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

---

## 2026-08-30 · from the LP-UI-004 review — three defects, all mine

LP-UI-004 landed clean (803 / 70 / 3, matching the re-measured figures), and then
found two failure modes in the codemod itself and one in what it did to a token.
All three were verified independently before being accepted.

### A7 — the codemod's silence was not evidence, and neither were my greps

**The finding is right, and it is the sharpest one so far.** `PATTERN` matched
`{prop}-gray-{shade}` over eight props. `shadow` was not in the prop list, and
`white`/`black` are not numbered shades — so `shadow-gray-900/5`, `bg-white`,
`text-white` and `bg-black` **never became candidates**. They are absent from the
"NOT MAPPED" report rather than listed in it.

Which means a clean codemod run and a clean `rg gray-[0-9]` were **both true while
45 hardcoded neutrals remained**, and `bg-white` is precisely what pins an app to
light. Its measurement makes the cost concrete: 2,088 text nodes walked across
four screens in both themes, **147 dark-mode AA failures** before the follow-up
commit, almost all the same shape — dark `--foreground` at 1.17:1 on a `bg-white`
panel that never flipped. Zero after.

My acceptance criteria said `rg "gray-[0-9]"` returning nothing was the proof.
It was not. **Silence in a report means "did not match", not "nothing left."**

Fixed in `assets/codemod-gray-to-token.mjs`:

- `shadow` added to the mapped props.
- A `NEEDS_A_DECISION` pass that finds every `white`/`black` neutral and **reports
  it loudly without rewriting it.** The ticket proposed auto-mapping `white → card`;
  I did not take that, because its own commit message makes the better argument —
  the 43 were *judgement, not mechanism*: 38 wanted `card`, 2 wanted `popover`
  because they float, 2 were `text-white` on the accent and wanted
  `primary-foreground`, and a modal scrim is not a surface at all. Auto-mapping
  would have got four of those wrong and buried the decision in a mechanical diff.
  Reporting preserves the mechanism/judgement split the ticket correctly defended.
- Re-run against the converted tree: reports the two remaining `bg-black` scrims
  and nothing else, which is the right answer.

**LP-UI-004's acceptance greps are extended** (below), and they now apply to every
later ticket too.

### A8 — the mapping is many-to-one, and meaning fell through the gap

**Also right.** Wherever two distinct greys carried *different meaning* — a base
tone and its hover, text-on-inverted versus text-on-surface — the mapping
collapsed them onto one token and the distinction disappeared silently. Nothing
errored; the classes still resolved, just to the same thing. A code review over
ten commits found thirteen defects, twelve of this one shape.

The worst was contrast on an inverted surface. `ltv-calculator.tsx:247` and
`dti-calculator.tsx:502` are tooltip body copy on `bg-foreground`. `text-gray-300`
took the generic `→ text-muted-foreground` mapping and fell from ~12:1 to
**3.43:1 light / 2.63:1 dark** — below AA. Recomputed here independently and the
numbers match to a rounding error; the fix to `text-background/75` gives
**10.22 / 7.93**.

This is a limit of shade-based mapping, not a bug to patch: a codemod cannot know
what surface a class sits on. **A6 did not catch it either** — that pre-check only
paired backgrounds and text that were *both* being converted, and `bg-gray-900`
was not even in its background map. So the inverted-surface case was outside what
I measured. Recorded rather than fixed: the mapping stays many-to-one, and the
guard is the per-element contrast sweep the ticket built, which is now the
standard for every screen ticket.

### A9 — the codemod orphaned the token LP-UI-001 created

`--skeleton` exists because `--muted` is too close to the card surface in dark —
that is its own comment. The codemod then mapped `skeleton.tsx`'s `bg-gray-200/70`
onto `bg-border/70`, routing the one component the token was created for away from
it, leaving `--skeleton` with **zero consumers**. Now `bg-skeleton/70`. The two
colours are within 0.2% lightness so nothing moves; the point is the token has its
consumer back.

---

## LP-UI-004 acceptance greps — extended, and binding on every later ticket

```
rg "gray-[0-9]"            app components lib   # → nothing
rg -- "-(white|black)\b"   app components lib   # → only deliberate scrims
rg "217 91%|217_91%"       app components lib   # → nothing
rg "#[0-9a-fA-F]{3,8}\b"   app components lib   # → nothing outside comments
```

And the one that actually proves it: **a per-element contrast sweep in both
themes.** Walk every leaf node carrying visible text, resolve its colour against
its nearest opaque ancestor background, and apply the WCAG threshold for that
node's own size and weight. Greps prove a string is gone. Only the sweep proves
the screen is legible.

---

---

## 2026-08-30 · A10 — the asset called an unverified document "Verified"

Caught by Claude Code mid-LP-UI-005, before it shipped. **The most consequential
defect in the assets so far, and the only one that would have told a processor
something false.**

`assets/lib/status.ts` renamed the document status `completed` to **"Verified"**.
It should have stayed **"Completed"**, and the reasoning is domain reasoning, not
style:

- `completed` is the terminal state of the **processing pipeline** —
  `pending → classifying → classified → extracting → completed`. It means a model
  finished reading the document.
- This product tracks **stated versus verified** data as a first-class
  distinction. That distinction is the thesis of the whole redesign.
- So a document whose extraction finished has been read by a model and checked by
  **nobody** — and the asset was about to label it with the exact word
  `NEEDS_STATUS.verified` already uses for the case where a human really has
  confirmed it. Two different truths, one word, on the same screen.

In a mortgage compliance tool that is not a wording nit. It is a false claim about
whether a document has been checked.

The asset is corrected to the shipping labels — `Processing` / `Classified` /
`Completed` / `Needs review` / `Failed` — with the reasoning written into the file
so nobody re-opens it. The three-way rename of `pending`/`classifying`/`extracting`
to "Queued"/"Classifying"/"Extracting" is dropped too: the app says "Processing"
for all three, and splitting one word into three is a product decision this
redesign has no business making.

**What actually caught it was my own rule.** `SPEC.md` says only the *colour*
vocabulary is being unified and the words stay — it was written because LP-583 and
LP-581 argued that wording out. I then broke it in my own asset. The rule held
because Claude Code applied it to me rather than following the file.

**Observation, not a demand:** the tone is still named `verified`, so the corrected
entry reads `{ tone: "verified", label: "Completed" }`. Tones are internal and
never rendered, so no user sees the mismatch, but a developer might read it as a
contradiction. If the tone vocabulary is ever revisited, `positive` or `settled`
would carry the meaning without borrowing a word that means something specific in
this domain. Not worth churning mid-epic.

---

---

## 2026-08-30 · A11/A12 — from the LP-UI-005 review, and these are the serious ones

A code review over the epic found six defects. Five were one story, and the story
is that **my consolidation quietly removed guarantees the six original maps had.**
Both were verified independently before being accepted; the asset now carries the
corrected implementation rather than my draft.

### A11 — consolidating the maps also widened them

Each of the six maps I replaced was exhaustive over its own union —
`Record<LoanFileStatus, …>`, `Record<DocumentStatus, …>`, `Record<NeedsItemStatus,
…>`, `Record<NeedsItemPriority, …>`, `Record<EvaluationOutcome, …>`. My
`lib/status.ts` typed all six as **`Record<string, StatusMeta>`**, and paired that
with a `resolveStatus` that synthesises a fallback for any key.

Those two changes together removed the compile-time guarantee *and* the runtime
one in the same move. The proof it ran: deleting `withdrawn` from
`LOAN_FILE_STATUS` and `waived` from `NEEDS_STATUS` left `tsc` silent and the
suite green, and a withdrawn file then rendered as amber **"Withdrawn"** through
the fallback — a status the app has always had, quietly reclassified as an error.

**And my tests could not have caught it.** They asserted through `resolveStatus`,
which by construction cannot fail: it returns `{tone: "attention", label:
humanizeUnknown(value)}` for anything it does not know, so
`expect(meta.label).toBeTruthy()` holds for *every string*. A test that cannot
fail is not a test. They now index each map directly and assert that its keys
equal the hand-written union, so a new enum member cannot be skipped by a stale
test array.

Fixed: every map is typed to its own union again; `CalculatorStatus` is declared
in `lib/status.ts` because `CalculatorView.status` is `string | null` on the wire
with no frontend union, so that map is exhaustive over *something*; and
`resolveStatus` is generic in the key so passing a typed map does not launder it
back to `Record<string, …>` at the call site.

### A12 — `spin` was load-bearing, and I treated it as decoration

The worse one, because it is a production behaviour change hiding in a visual
refactor. My asset made `spin` the single source of truth for "the pipeline is
still working". `isTerminalStatus` feeds `documentsRefetchInterval`.

So an unrecognised status — no entry in the map, therefore no `spin` — counted as
**terminal**. A backend that grew a new in-flight status would have stopped the
document list and drawer from refetching, **parking the document until someone
reloaded the page by hand.** It also coupled polling to a purely visual property:
`classified` carries its own label, and a designer dropping its spinner as a
tidy-up would have halted polling mid-pipeline.

Fixed with an explicit `IN_FLIGHT` table that fails the safe way — an unknown
status counts as *in flight*, because polling one state too long costs a request
while stopping early strands a document.

### What this run has taught, which belongs in the standing note

Ten of the twelve defects so far are mine, and the two most dangerous —
A10 ("Verified" on an unverified document) and A12 (polling stops silently) —
were **not visual at all**. They were a design asset making claims about domain
meaning and runtime behaviour that were not mine to make.

The pattern is consistent: a design system can safely dictate colour, spacing and
type. The moment it touches a *word with domain meaning* or a *value something
else reads*, it needs the same scrutiny as application code — and the person best
placed to apply that scrutiny is the one holding the codebase, not the one holding
the palette.

---

---

## 2026-08-30 · A13-A16 — from the LP-UI-006 review

Four more, and two are repeats of failure modes already recorded here. The assets
now take `tailwind.config.ts` and `lib/status.ts` from the implementation rather
than from my draft.

### A13 — `CalculatorStatus` was exhaustive over the wrong set

A11 restored exhaustiveness and I checked that each map was exhaustive over
*something*. That was not enough. `CALCULATOR_STATUS` was typed against the
display map it replaced, not against its **producers** — there are three, all
reaching it through `CalculatorsSection`'s `Tile`: `DtiTile` (`DtiLimitStatus`
plus a literal `"unknown"` for a gated DTI), `LtvTile` (`LtvLimitStatus`), and
`CalcTile` (`CalculatorView.status`).

`unknown` and `binding:*` were in none of them. `services/calculators.py:573`
emits `"binding:" + binding_key`, so those reached `humanizeUnknown`, which only
swaps underscores — and a `variant="dot"` tile carries its label **only** in
`title` and an sr-only span. So hovering the Maximum-loan tile showed the tooltip
**"Binding:dti"**, and a screen reader read it aloud. The map this replaced fell
back to a silent grey dot, so **the consolidation introduced this leak.**

Exhaustive over *something* is not the test. **Exhaustive over the producers is.**

### A14 — one unknown need blanked the entire Needs page

`groupNeeds` indexed the group map raw and pushed into the result:
`buckets[NEEDS_GROUP[need.status]].push(need)` throws a `TypeError` on any status
the build does not know, and `NeedsDashboard` calls it *before* rendering a single
card — so one unrecognised need took out the whole page, including the needs it
understood perfectly well. `outstandingNeedsCount` had the quieter version,
under-counting in silence.

The shape predates this epic, but the consolidation was the moment to fix it and
did not. The sting, in its own words: the previous review hardened
`isTerminalStatus` against exactly this and wrote a comment explaining why, while
the call that runs first kept the raw index. Both now fall back to
`needs_action`, matching `resolveStatus`'s `attention` default.

### A15 — the density retune re-armed iOS auto-zoom

`input.tsx` and `textarea.tsx` shipped `text-base … md:text-sm` deliberately:
mobile Safari zooms the viewport whenever a focused control computes under 16px,
and never zooms back out. My retune flattened both to `text-sm` — 13px at every
breakpoint.

The obvious repair fails, and that is the interesting part: `text-base md:text-sm`
is the standard guard, but **I retuned `base` to 14px**, still under the
threshold. The scale now carries a named `field` size at exactly `1rem`, and both
controls wear `text-field md:text-sm`, so the reason travels with the token
instead of living in someone's memory.

### A16 — `fontSize` was in `theme.extend`, seventeen lines under the comment about `fontWeight`

The A1 trap, again, in the same file. `extend` merges, so the stock ramp survived
above `2xl`: `text-3xl` resolved untracked while `xs`…`2xl` were retuned — and
`text-3xl` has **six live sites** (the dashboard stat numbers, the marketing hero,
four DTI/LTV headline figures).

Worth noting what it did *not* do: moving `fontSize` to `theme` replaces the scale,
which would have made those six resolve to nothing — the exact silent-weight-loss
failure A1 caused with `font-bold`. It added `3xl` to the scale explicitly instead,
keeping stock size and line-height and supplying the tracking the scale wanted.
The lesson from A1 was applied rather than repeated.

## 2026-08-30 · A17 — from the LP-UI-009 review, and this one is the ticket's fault

### A17 — an acceptance criterion that forbade the feature it was written for

LP-UI-009's second checkbox read *"Reads from the queries already cached by the
file layout — no extra fetches."* Checked against the code rather than assumed:
`app/(protected)/loan-files/[id]/layout.tsx` caches exactly **one** query,
`useLoanFile`. DTI, LTV and reserves are fetched by the Verification tab, because
that is the tab that owns them — and the entire premise of the rail is that a
processor should not have to go to Verification to see those three numbers. A
criterion forbidding those requests forbids the rail.

What the criterion *meant* is **no duplicate requests**, and the implementation
meets that: on Verification the rail's dti/ltv/reserves cost zero, deduped by
React Query key. Measured deltas were +3 on Overview, +4 on Documents, +1 on
Verification.

The criterion is reworded in TICKETS.md. The general form of the mistake: an
acceptance criterion asserting a fact about the *existing* code ("already
cached") has to be checked against that code when it is written, not when it is
tested — otherwise it ships as a constraint on the new work rather than a
description of the old.

**Accepted, not fixed:** the rail is `hidden xl:block`, so below 1280px it still
mounts and its four always-on queries still fire for a user who cannot see it.
Every fix costs more than the bug: the viewport is only known after hydration, so
deferring the queries trades four requests on narrow screens for a guaranteed
skeleton flash on every wide one. Recorded here so the next person does not
rediscover it as a defect.

**Not a defect, checked:** the DTI-only "Gated" wording is right — `gated` exists
on `dti.py` and has no counterpart in `ltv.py`, so there is no gated LTV to
mirror.

## 2026-08-30 · A18 — from the LP-UI-012 review

### A18 — the serif carries two registers, and only the italic one is reserved

LP-UI-012 renders the login page's thesis line in **upright** Plex Serif, and
LP-UI-003's brief says *"Plex Serif italic appears in exactly one place, text
quoted verbatim from a document"*. Raised as a contradiction that would force
either a reworded rule or a drop to sans.

Neither, because the rule is about a face the login page does not use. Checked
in the tree: the only `font-serif` today is `app/(auth)/login/page.tsx:44`, with
no `italic`, and LP-UI-029's verbatim snippet — the reserved use — is specified
as serif *italic* and has not shipped. Two faces, and the sentence governs one of
them. It is not false; it is silent about the other.

So the rule stands and gains a second clause:

- **Plex Serif italic** — text quoted verbatim from a document. Reserved,
  exceptionless, and the reason it reads as "the document speaking" without a
  label. Nothing decorative may borrow it.
- **Plex Serif upright** — the product speaking about itself, in the pre-
  authentication chrome. One line on the login page, and no use inside the
  working surfaces, where a serif that is not a quotation would teach against
  the rule above.

Recorded rather than resolved by deleting the line because the distinction is
load-bearing: the value of "serif means the document" comes from being
exceptionless, and an upright face used somewhere a processor never meets a
document costs that nothing. What would cost it is upright serif appearing on a
file screen, which this clause forbids.

Worth noting the dependency: upright serif only renders at all because the
LP-UI-003 review corrected `plexSerif` from `style: ["italic"]` to
`["normal", "italic"]`. Before that this line would have silently fallen back to
Georgia.

---

## 2026-08-30 · A19 — from LP-UI-015, and this one is the ticket's fault too

### A19 — "current user" is not a filter this product can express

LP-UI-014 asks saved views to *"Support **current user** as a filter value so one
shared view serves the whole team"*, with an acceptance criterion *"Current user
resolves per viewer"*, and the Pipeline mockup shows the pills **My files 18** and
**Unassigned 2**.

Checked against the models rather than assumed: **a loan file has no owner.**
`LoanFile` carries no `assigned_to_user_id`, there is no user/file association
table, `loan_officer_name` / `loan_officer_email` are free text describing an
EXTERNAL contact, and `uploaded_by_user_id` lives on the document, not the file.
"My files" has nothing to resolve against, and "Unassigned" is every file.

LP-UI-015 was right to build `SavedViewFilters` with `extra="forbid"` rather than
accept the field and quietly drop it — a view that silently ignores half of what
it claims to filter on is the failure this product exists to prevent. A client
sending `{"assigned_to": "current_user"}` gets a 422.

**The criterion is removed from LP-UI-014, not deferred inside it.** File
assignment is a feature, not a filter: a column, a migration, an assignment UI, a
backfill for existing files, and a decision about one owner or several (a
processor plus a reviewer is the obvious second case). It needs its own ticket and
its own product decision. The two mockup pills go with it.

The general form, and it is the same shape as A17: a ticket may not assert a
capability of the existing data model without checking the model when the ticket
is written. Both times the design assumed a field the schema does not have.

## 2026-08-30 · A20 — a design consequence of LP-UI-017, before LP-UI-018 is built

### A20 — the ledger's agreement verdict is not always the engine's

LP-UI-017 builds the reconciliation read model — the comparison this whole
redesign is named for. It correctly reads the income variance threshold off
`XSRC_INCOME_STATED_VS_DOCUMENTED.threshold` rather than restating `10`, so the
ledger and the cross-source rule agree by construction.

**Except under a lender overlay.** LP-80 makes that threshold overrideable per
lender by `rule_id`, and the read model does not resolve overlays — so for a file
whose lender has widened or narrowed the variance, the ledger compares against the
default while the engine compares against the overlay. Disclosed in the service's
own docstring rather than hidden, which is the right call, but it is a live
design constraint for **LP-UI-018** (the ledger screen) and it must not be
discovered during implementation.

The design consequence: **where a finding exists for a row, the finding is the
authority and the ledger row defers to it.** The ledger screen may not paint its
own agree/differ verdict as the answer over a row the engine has already ruled on
— it shows the finding's verdict and its own comparison as the evidence beneath.
Rows with no finding keep the ledger's verdict, which is where the read model
earns its keep (the `not_stated` direction has no finding at all).

This is SPEC's "an aggregate must reuse the predicate its detail screen uses"
applied to a case where reuse is only *mostly* possible. Where it cannot be
complete, the screen must say which source it is showing rather than average them.

## 2026-08-30 · A21 — from LP-UI-018, and it is LP-UI-005's undercount

### A21 — the status vocabulary had seven domains, not six

LP-UI-005 is titled *"One status vocabulary"* and opens *"Six independent status
maps"*. Building the ledger screen turned up a seventh: **`finding.status`**
(red / yellow / green) had no map at all.

The undercount is understandable and worth naming precisely, because it is the
A13 shape again. My ticket listed `lib/verification/rule-findings.ts` as a call
site — but that file's map is the rule **outcome** (satisfied / violated /
unknown), which is a different axis from the finding's **severity**. Two maps in
one file, counted as one. The severity axis had no consolidated home, so a
processor met a seventh amber.

`FINDING_SEVERITY` now sits in `lib/status.ts` beside the other six:
`red → blocking / "Blocking"`, `yellow → attention / "Warning"`,
`green → verified / "Passed"`. Recorded rather than silently absorbed, because
LP-UI-005's acceptance criterion *"the six old maps are deleted, not left
orphaned"* was satisfiable while a seventh survived — the count was load-bearing
and it was wrong.

**The general form:** when a ticket asserts a COUNT of things to consolidate, the
count is an acceptance criterion and has to be derived from the code, not from
the survey that motivated the ticket. Two maps living in one file read as one.

**UPDATE (LP-UI-028): eight, not seven.** `STATUS_BADGE` on the rule-validation
admin screen was a further independent map with its own colour language, found the
same way. It is now `VALIDATION_STATUS` in `lib/status.ts`, typed
`Record<ValidationStatus, StatusMeta>` against a real union. `grounded_starter`
takes the **ai** tone rather than `neutral`, and that is the whole point of that
screen: the status records *where the value came from* — researched against the
Selling Guide, pending a domain expert — not whether it is correct, which is the
`ai` tone's own definition. Rendered `neutral` it read as "nothing to do here" on a
screen that exists to surface what nobody has confirmed, where 121 of 121 items sit
in that state.

The count was wrong twice, which retires the count as a criterion: **do not assert
how many vocabularies exist.** The durable criterion is that every status a screen
renders comes from `lib/status.ts`, checkable by grep at any time.

### Operational note — an unstaged amendment is an invisible amendment

A20 was written the night before LP-UI-018 precisely so the ticket would honour
it, and sat unstaged in the shared working tree. LP-UI-018 built the ledger with
no reference to findings and found the amendment only while staging its own work,
then implemented it. It landed correctly, and it landed on luck.

Amendments written for a specific upcoming ticket are only binding once
committed. Where this session cannot commit, the amendment must be stated in the
check-in that reaches the implementing session as well as written to the file.

## 2026-08-30 · A22 — the pattern this epic keeps finding, and what to do about it

### A22 — "one file, two screens, different numbers" is systemic, not incidental

Six instances so far, all found by verifying rather than by anyone reporting a
bug, and every one of them a *live* disagreement a processor could have hit:

1. **LP-UI-013** — the dashboard counted blocking findings with its own filter,
   ignoring the confidence cutoff and missing AI findings. A file its own
   verification screen calls clear read as blocked, and vice versa.
2. **LP-UI-013** — the needs count put `received` in the waiting set, so the
   dashboard said "Waiting on 5" against the file screen's 3.
3. **LP-UI-017** — the ledger compared income without the engine's `quantize`, so
   10.04% variance was a pass to the engine and a disagreement on the ledger.
4. **LP-UI-018** — the ledger deferred to `xsrc.income.employer_name_consistency`,
   a rule LP-606 **retired** precisely because it disagreed with IN-5 on real
   files. The ledger had adopted the answer that lost.
5. **LP-UI-019** — three readers of one document list had two definitions of
   "in flight", so "Processing 3 of 18" described no set on the screen.
6. **LP-UI-020** — the file context rail printed the **legacy** sweep's severity
   counts under the **governed** engine's words: "Must fix 0" on a file with ten
   open violations. The block had no test at all.

This is not six unrelated bugs. It is one architectural condition: the codebase
carries **two generations of verification** (legacy sweep and governed engine)
plus retired-but-still-defined rules, and nothing structurally prevents a new
surface from binding to the wrong generation. Every new read model is a fresh
chance to pick the loser.

**What this epic can do, and has:** the SPEC rule ("an aggregate must reuse the
predicate its detail screen uses"), A20's deference rule, and now a test
asserting every rule the ledger defers to is still in `CROSS_SOURCE_RULES`.

**What it cannot do, and should be raised as product work:** the two generations
need a stated end-state — is the legacy sweep being retired, and by when? Until
that is decided, every screen in Epics C–G is a new place for the two to
disagree, and the reviews will keep finding them one at a time. This belongs in
the backlog as its own item, not inside a UI ticket.

**RESOLVED, and the answer is worse than the question** (LP-UI-021). The 91 is
**75 governed + 3 deterministic cross-source + 13 legacy AI sweep**. Two faults,
not one:

- The headline merged three generators into one figure, collapsing the very
  separation LP-375 keeps structural. `open_in_scope_findings` queries `Finding`
  with no origin filter — right for "can this file submit", wrong as a headline.
  The alert now names each system, and `breakdown_by_system()` counts **per
  system** with a real `other` else-branch, so a fourth generator gets its own
  number rather than inflating an existing one.
- **The missing 3 appear on no screen at all.** The governed tabs read
  `rule_findings`; the "Old findings" tab reads `data.findings`, which is
  `ai_cross_source` only. The three deterministic `xsrc.*` findings are in
  neither — and **two of them come from `xsrc.income.employer_name_consistency`,
  the retired rule from instance 4 above.**

**The production consequence, stated plainly:** those three findings are *open*,
they are *counted as blocking*, and the alert says they can be applied or
overridden — but **no screen offers either action, or lists them at all**. A loan
file can therefore be blocked from submission by findings a processor cannot see
and cannot resolve. That is not a UI defect. It is the retirement being half
done: the rule stopped running, and its open findings were never migrated,
resolved, or given a home.

**This is now the top open item and it needs a product decision, not a ticket:**
what happens to open findings from retired rules? Backfill-resolve them, migrate
them to their successor, or give the deterministic cross-source family a surface.
Until that is answered, "blocked by something invisible" is live behaviour.

## 2026-08-30 · A23 — from LP-UI-025/026, and it is the largest gap the epic has found

### A23 — the lender overlay editor writes a column the rule engine never reads

**Verified independently, not taken on report.** Three checks, all confirming:

- `LenderOverlay(...)` is constructed in exactly three places, all Python
  constants: `verification/overlays/starter.py` (UWM, Sun-West) and
  `verification/overlays/samples.py`. Never from the database.
- `verification/registry.py:127` builds
  `RuleRegistry(overlays={**SAMPLE_OVERLAYS, **STARTER_OVERLAYS})` — two
  hardcoded dicts keyed by slug, and nothing else.
- The `lenders.lender_overlays` column is read in exactly three modules, all of
  them the admin surface: `services/`, `api/` and `schemas/overlay_admin.py`.
  Nothing under `app/verification/` touches it.

So: **an admin can override a lender's rule threshold, and nothing happens.** The
value is stored, audited, counted, and displayed as that lender's headline
configuration on the lenders list — and every loan file at that lender is still
evaluated against the investor default. ADR-193 deferred the reading half and
LP-87 built only the writing half; the deferral's own words ("currently unused")
are still literally true of the engine.

LP-UI-025 did not cause this, but it is what made it visible: promoting the
override count to a lender's headline turns a dormant column into a claim.
LP-UI-026 then found the editor's own introduction saying *"Editing a threshold
changes what enforcement uses for this lender"* — a screen telling an admin their
change is live when it is not, which is the worst thing that editor could do. The
copy now says "Recorded, not yet applied", with a comment to delete it when the
column is wired.

**UPDATE (LP-UI-027): the gap is three layers, not one.** The estimator built for
blast radius had to establish what it could actually measure, and found:

1. **The column is unread** — `registry.py:127` uses only the two constant dicts.
2. **The overlay-aware engine is uncalled.** `services/verification_engine` holds
   the only `evaluate()` that resolves overlays at all, and it has no production
   caller. Verified: its only importer anywhere in `app/` is the new estimator
   itself, and the codebase already says so in its own words at
   `finding_source_matching.py:193` — *"verification_engine has no caller"*.
3. **No finding exists for any rule an overlay can target.** Zero findings for
   any `conv.*`, `fha.*` or sample rule id.

Taken together, the lender-overlay capability is **inert end to end**, not merely
missing its storage wiring. That matters for how it gets fixed: wiring the column
into the registry is necessary and not sufficient, because nothing calls the
engine that would consume it.

It also validates a deviation LP-UI-027 made deliberately. The ticket asked for
blast radius "estimated against each file's last completed run"; built that way it
would have answered **"no files affected" for every proposal** — the most dangerous
possible answer, indistinguishable from a correct one, reading as reassurance, on a
screen where an admin acts on it. It evaluates the pure engine twice with the
proposed thresholds swapped in and diffs instead, which works today and keeps
working once the column is wired.

**This is a product decision, not a UI ticket:** finish LP-87's other half (wire
the column into the registry, and call the overlay-aware engine, with the
precedence and caching questions that implies), or state that overlays are
configuration-only for now. The honest copy is a stopgap, not an answer — an admin
screen whose whole purpose is an action that does nothing is not a screen worth
keeping in that state for long.

### A20, corrected by A23

A20 warned that the reconciliation ledger does not resolve LP-80 lender overlays,
so under an overlay lender the ledger and the engine could disagree. **That
divergence does not exist today, because the engine does not resolve stored
overlays either** — both read the same defaults. A20's mitigation (where a
finding exists, the finding is the authority) remains right and costs nothing.

But the risk inverts the moment A23 is fixed: wiring the column into the registry
makes the engine overlay-aware while the ledger stays default-aware, which
*creates* the disagreement A20 anticipated. **Whoever wires the column must change
`reconciliation.py` in the same change.** Recorded here because the two live in
different parts of the codebase and nothing connects them.

## 2026-08-30 · A24 — from LP-UI-030, and the first half corrects MY answer to LP-UI-029

### A24a — my 99.1% figure measured the wrong thing

LP-UI-029's blocker was "no bounding boxes exist; is snippet matching viable?" I
answered yes, on **99.1% page+snippet coverage**. That number is real and it is
the wrong number: it measured the snippet being **present in the extraction
record**. What decides whether a highlight can be drawn is the snippet being
**findable in the PDF's text layer**, by the mechanism that will draw it.

LP-UI-030 measured that, over 105 real stored PDFs, 752 current-extraction
fields, using `page.search_for()` — the same call LP-UI-031 will use, so it is
the instrument and not a proxy:

| | |
|---|---|
| 548 (72.9%) | snippet found on the cited page |
| 28 (3.7%) | snippet findable, but the cited page does not exist |
| 89 (11.8%) | absent from the text layer entirely |
| 83 (11.0%) | on a scan, with no text layer at all |
| 4 (0.5%) | cited page out of range and absent |

**A derived box is reachable for about 77% of fields, not 99%.** No whitespace
normalisation was applied, so 77% is a lower bound. 12 of 105 documents are scans
for which no highlight is derivable at all.

The design consequence is that the "page known, spot not located" field state I
added to the Review screen is not an edge case to be drawn small — it is roughly
one field in four, and on a scanned document it is every field. It has to be
designed as a first-class state, and the Review screen must be legible with no
boxes at all.

**The lesson, and it is mine:** I answered a feasibility question with the
closest number to hand rather than the number the question was about. Coverage of
a *record* is not coverage of a *capability*. Where a ticket is unblocked by a
measurement, the measurement has to be taken with the mechanism that will do the
work.

### A24b — 4.3% of fields cite a page the document does not have

The sharper finding, and it is not about boxes at all. The measurement script
buckets a recoverable snippet as `found_on_another_page` when the cited page is
in range, and `oob_found_elsewhere` when it is not. Its output carries
`oob_found_elsewhere: 28` **and no `found_on_another_page` key at all** — and a
`Counter` only holds keys it incremented, so that bucket is zero.

So no field cites a wrong-but-existing page. All 28, plus the 4 out of range and
absent, cite a page number **the document does not have**: **32 of 752 fields,
4.3%.**

That is categorically different from an attribution drifting by one page. It is
the model **inventing a page number** — "p.7" of a three-page letter — and
**LP-UI-018's ledger renders that string to a processor as provenance, as fact, on
a compliance screen.** A processor who turns to p.7 to check a figure finds no
p.7, and the product's central promise — *here is where this came from* — is
false 4% of the time.

**Design consequence, binding on LP-UI-031 and on the ledger:** a page citation
must be validated against the document's page count before it is rendered as
provenance. Where the cited page does not exist, the ledger says the snippet was
found and the location is unknown, rather than printing a page number that is not
true. This is cheap — the page count is already known wherever the PDF is opened.

**Product consequence, for the user:** page attribution is wrong on ~4% of
extracted fields today. Whether that is acceptable at pilot, and whether the
extraction prompt or a post-hoc validation step should fix it, is a product and
model question, not a UI one.

## 2026-08-30 · A25 — LP-UI-031 acted on A24b in the reviewer; the ledger still prints `p.N`

A24b made page-citation validation binding on **LP-UI-031 and on the ledger**.
LP-UI-031 has done the first half and not the second, and the gap is worth
naming rather than leaving to be discovered.

**Done, in the reviewer.** `find_field_boxes` knows whether the cited page
exists, and `cited_page_exists=False` travels with the result. The field row says
*"The extraction cited a page this document does not have"* — and, where the text
was located elsewhere, that it is being shown where it actually appears. The
better page is never substituted silently; a provenance trail that quietly
corrects the model is not one.

**Not done, in the ledger.** LP-UI-018 renders `p.N` from the finding's stored
citation with nothing checking N against the document's page count. On ~4% of
fields that string is invented. The reviewer now contradicts the ledger on the
same document: one screen says the page does not exist, the other prints it as
fact.

Closing it needs the page count where the ledger renders a citation, which the
ledger does not have today — it reads findings, not documents. That is a small
piece of plumbing and a real one, and it is not field↔box linking, so it is
recorded here as an open item rather than folded into LP-UI-031.

**Until it is closed, the honest reading is:** the document reviewer tells the
truth about page attribution and the ledger does not.

## 2026-08-30 · A26 — from LP-UI-032: a tier with no producer, and an SSN on the screen

### A26a — "Verified (human-confirmed)" cannot occur, and needs a product decision

LP-UI-032's first tier is human confirmation. Searched exhaustively:
`create_extraction_version` is written by the extraction task and the seed script
and by nothing else — no endpoint, service or model lets a processor confirm or
correct an extracted field value. The LP-44 document-type override is the only
human correction nearby and it corrects the TYPE, then re-extracts.

So the tier is implemented, tested, and **unreachable**. `humanConfirmed` is
always false because nothing can set it.

**This is not a UI gap.** "A processor marks a field as checked" is a workflow with
real questions behind it: does confirming a field survive re-extraction, does it
travel to the underwriter, is it auditable, does it block or unblock anything. The
screen can render the answer; it cannot invent the question. Until that exists,
the reviewer has three live tiers, not four.

### A26b — the fields pane was printing unmasked Social Security numbers

Found by looking at a real credit report while checking tier rendering.
`MASKED_FIELD_KEYS` held exactly two keys, `employee_ssn` and
`account_number_masked`, while the corpus carries `borrower_ssn`,
`co_borrower_ssn`, `spouse_ssn_masked`, `taxpayer_ssn_masked`,
`borrower_ssn_or_itin` and others. Every one of those rendered **in the clear**.

Fixed in LP-UI-032: the backend answers `sensitive` from the same `identity`
category of `critical_fields.yaml` that makes those fields critical — one list, so
an SSN field added to it is masked by construction — and the frontend keeps its own
set as a floor so a backend that stops answering cannot un-mask anything.

**The general shape, which is worth more than the fix:** a deny-list of things to
hide is wrong by default for PII. It protects exactly what someone remembered, and
it fails silently and invisibly — nothing errors when an SSN is printed. The
identity list is now derived from a list that has a drift guard over the schema
specs, so a new identifier field fails a test rather than reaching a screen. Any
other place that masks by enumerating keys has the same defect and has not been
audited.

### A26c — the ticket's own two thresholds contradict its override rule

0.97 for critical fields AND criticality overriding confidence cannot both bind:
if a critical field is checked whatever its number, no number decides anything.
Resolved toward the AC's explicit sentence (a 0.97 loan amount still gets flagged);
`CONFIDENCE_CRITICAL` is kept and parity-tested against the stylesheet with the
tension recorded at its definition. Worth a decision if the intent was the other
reading — that critical fields use the HIGHER bar rather than always flagging.

### A26d — the ticket's three tiers do not cover the data

74% of stored fields carry no confidence at all. A fourth tier, "Not rated", in
neutral. The measurement is in `docs/tickets/LP-UI-032.md`.


## 2026-08-30 · A27 — from the LP-UI-032 review: a guard with a hole shaped like a spelling

A26b closed the SSN exposure and named the general shape: *any other place that
masks by enumerating keys has the same defect.* Both findings here are that
sentence coming true, in the two places the fix could not reach.

### A27a — `ssn` does not match `social_security_number`

The drift guard is the right instrument and it had a hole. `CRITICAL_SHAPE`
tested for `ssn` and `itin`; the schema specs also spell the same thing out as
`social_security_number`, `social_security_number_2`, `taxpayer_tin`,
`spouse_tin`, `payer_tin`, `ein`, `employer_ein`, `i94_number`,
`uscis_or_a_number`, `date_of_birth`. None of those substrings contain `ssn` or
`itin`, so **38 identity keys were never forced into a decision**, were in
neither list, and answered `is_sensitive() == False`.

`social_security_number` is a shipped spec key. It would have rendered a Social
Security number in the clear — the identical defect A26b fixed, one spelling
over, and the guard built to prevent exactly that could not see it. Three of the
38 carry data in the corpus today (`date_of_birth` ×8, `borrower_date_of_birth`,
`employer_ein` ×14).

The same hole covered money that names itself with a noun instead of a suffix:
`cash_to_close`, `total_closing_costs`, `monthly_principal_and_interest`,
`total_assets`, `total_liabilities` — the figures a borrower is actually quoted.
None of them end in `_amount`. 92 keys are now classified; the regex covers the
spelled-out identifiers and the noun-shaped money.

**The lesson is about how a shape guard fails.** It fails on the vocabulary its
author had in mind, and it fails silently, because an unmatched key is
indistinguishable from a key that was considered and found ordinary. A regex over
names is still the right tool — it caught 220 keys — but it needs to be tested
against the whole key universe by reading what it does NOT match, which is the
only way this was found.

### A27b — being classified is not the same as being classified where masking looks

`is_sensitive()` reads `critical.identity` and nothing else. A field filed under
any other category is critical, flagged in the UI, and **still rendered in the
clear** — and the drift guard cannot catch it, because the field *is* classified.
`test_a_personal_identifier_lands_in_the_group_that_gets_MASKED` closes that: a
name matching an anchored SSN/TIN shape that is declared critical must be in
`identity`. Verified by moving `borrower_ssn` to another category, which fails.

### A27c — the catch-all rendered every value unmasked, and the label alone cannot fix it

`extractionFields` masks by field KEY. The catch-all (`additional_sections`) is
keyed by a free-text LABEL the model wrote, so there is no key to look up, and it
masked nothing at all. That is the worst possible place for the gap: **the
catch-all is by definition the fields nobody classified**, which is exactly where
an unclassified identifier ends up. Measured on the corpus: a nine-digit tax id
under "b Employer's social security number", plus eleven other
identifier-labelled values, rendering in the clear.

The fix has to read the label AND the value, and the reason is a real pair of
rows on a real pay stub:

| label | value | what it is |
|---|---|---|
| `b Employer's social security number` | 9 digits | a tax identifier |
| `Social Security - YTD` | `$4,200.00` | a withholding amount |

Masking on the label alone hides the processor's YTD figure — a worse bug than
the one being fixed. Masking on the value alone misses an eight-digit brokerage
account number, which no rule can distinguish from any other number without its
label. So: money and rates are excluded first, then a bare 9+ digit run or an SSN
shape is an identifier whatever the label claims, and below that the label decides.

### A27d — masked and readable are not the same list, and this split is not domain-reviewed

Not every identity field should be hidden. Verifying a date of birth against the
1003, or an employer's EIN against the W-2, **is the processor's job**, and a
masked value cannot be verified. So `critical.identity_readable` holds the fields
that are critical (a wrong one corrupts an identity match) but rendered: dates of
birth, EINs, professional licence numbers, account tails. `identity` — hidden —
holds personal identifiers: SSNs, personal TINs, immigration numbers.

Which side a field belongs on is a judgement about what a processor needs to read
versus what should never be on a screen, and it has not been reviewed by the
domain expert. It is the kind of question she should be asked directly.


---

## 2026-08-30 · A29 — mine, from checking LP-UI-032: a second definition of "identifier"

### A29 — the masking list was authored, not derived, and an older one already existed

LP-UI-032 and its review closed a live PII leak, and the fixes are right. Checking
them turned up something the ticket did not look at.

`field_criticality.py` imports stdlib and `yaml` and nothing else. It does not
consult `_PII_FIELDS` in `verification/snapshot/documents_section.py` — an
existing map of **82 field names** already classified by `PiiKind`, with a
pre-masked flag, used by the snapshot and scrubbing layer all along.
`social_security_number` was already in it as `(PiiKind.SSN, False)`.

**The codebase already knew that field was an SSN. The masking that leaked it was
not asking the list that knew.**

So "is this field an identifier" is now answered by two independently maintained
lists, and they disagree. Compared directly:

- **22 fields** the snapshot layer classifies as PII and does *not* treat as
  pre-masked are absent from the reviewer's identity groups — among them
  `account_number`, `aba_routing_number`, `wire_ach_trace_number`,
  `wire_or_remittance_instructions`, `document_discriminator`, `document_number`,
  `passport_number`. All are `PiiKind.ACCOUNT`. **No SSN-kind field is in the
  gap**, so the acute exposure A26b/A27 fixed really is closed.
- **11 fields** in the reviewer's identity groups are absent from `_PII_FIELDS`,
  mostly dates of birth and professional licence numbers.

**This is not "22 fields are leaking."** Several of the 22 are arguably meant to
be readable — a processor verifying a bank statement may need the account number,
which is exactly the `identity` / `identity_readable` split A27d drew and flagged
as not domain-reviewed. The defect is that the question is **answered twice, by
two lists maintained separately**, on the one topic where divergence means a
disclosure rather than a wrong number.

This is A22's pattern at its highest stakes — the seventh instance, and the first
where the cost is PII on a screen rather than a number that disagrees with another
number. The epic's own SPEC rule applies exactly: *an aggregate must reuse the
predicate its detail screen uses, not restate it.*

**Recommendation, for the user rather than for a ticket.** Derive the reviewer's
identity groups **from `_PII_FIELDS`**, so the yaml records only the readable /
hidden decision per field — the genuinely new judgement — instead of re-listing
which fields are identifiers at all. And put the readable / hidden split to the
domain expert alongside the critical-field list A26 already flagged as
un-reviewed.

---

## 2026-08-30 · A28 — from LP-UI-033: the Verified tier now has a producer, and a correction fixes nothing

### A28a — A26a is closed

LP-UI-032 reported "Verified (human-confirmed)" as a tier no field could reach,
because no action anywhere in the product confirmed an extracted value. LP-UI-033
builds that action: `Enter` accepts, `E` corrects, `R` rejects, and a verdict is
recorded per (extraction, field) in `field_reviews`. The tier is live, and a
processor's accepted field renders as Verified and drops out of the keyboard loop.

The design questions A26a raised are answered, and the answers are in ADR-393: a
verdict sits beside the extraction rather than inside it, so the model's own value
stays answerable; and it is keyed on the extraction version, so a re-extraction
retires it rather than attaching a person's name to a figure they never saw.

### A28b — a correction is a note, not a fix

**Nothing consumes a corrected value.** The rule engine reads `extracted_data`,
which a correction deliberately does not touch. So a processor can read the pay
stub, see that the extracted gross pay is wrong, type the right figure — and the
DTI will still be computed from the model's number. The screen will show the
correction; the verification will not.

This is the honest state and it is not a small gap. It is the difference between a
correction being a record of disagreement and a correction being a repair, and a
processor has every reason to assume the second.

Closing it is a verification-layer decision, not a UI one, and it has its own
questions: does a correction re-trigger a verification run; does it invalidate
findings that cited the old value; does a corrected value need its own provenance
in the snapshot so a rule can say where its input came from; and what happens to a
correction when the field it corrects is one the LP-508 list already distrusts.

**Until it is closed, the reviewer must not imply otherwise** — which is why the
correction renders beside the model's value rather than replacing it outright.

### A28c — the same fact was computed in two places again

`Enter` recorded the verdict, the API stored it, the field left the keyboard
queue, and the mark beside the row went on saying "Check this". `buildQueue` knew
about verdicts; `tierInputFor`, written in LP-UI-032 before verdicts existed, did
not. Both callers now derive the tier through one function.

Third time in this epic (A20/ADR-391, ADR-392, this): a value derived in two
places disagrees the moment one of them learns something. Worth reading as a
standing hazard rather than three incidents — when a second caller needs a derived
fact, the fix is to reach for the first caller's function, not to rebuild the
mapping beside it.

## 2026-08-30 · A30 — from the LP-UI-033 review: a documented mechanism that never runs

### A30a — the CASCADE that retires a verdict does not fire on re-extraction

ADR-393 said a superseded extraction's verdicts "go with it" through the
`ON DELETE CASCADE` on `extractions`, and the migration docstring said the same.
**Re-extraction deletes nothing.** `create_extraction_version` demotes the current
row to `is_current = False` and inserts a new one, because prior versions are kept
for audit — and no code path deletes an `Extraction` at all.

The behaviour the ADR wants is correct anyway: a verdict is keyed on
`extraction_id`, so a new version simply has none of its own. But the *mechanism*
is the key, not the cascade, and the difference is not pedantic. A cascade is a
guarantee about deletion; a key is a guarantee about identity. Anyone who changed
re-extraction to update a row **in place** — a plausible optimisation — would keep
every verdict attached to values nobody reviewed, and the cascade the ADR pointed
at would not save them.

`TestReExtraction` pins all three facts, including that the superseded version
*keeps* its verdicts. That last one is what shows the cascade is not what runs: if
reviews really died with their extraction, the history assertion would be empty.

**The general shape:** the ticket's own open-items list named "no test that a
re-extraction drops the verdicts" as the gap to attack first. That instinct was
right, and the test it asked for would have failed for a reason nobody expected —
not "the cascade is broken" but "the cascade was never involved". A test written
against a mechanism you have not confirmed runs will pass or fail for reasons
unrelated to the mechanism.

### A30b — a rejection rendered as nothing at all

`tierInputFor` set `humanConfirmed: false` for a rejection, with a comment saying a
rejection "is not confirmation ... and it must keep its mark". It kept no mark.
`false` only returns the field to the ordinary path, and on that path a
non-critical field rated at or above the standard threshold is `confident` — which
renders **null** by design. A processor could reject a value and watch their own
decision vanish from the row it was made on.

Fixed with a `rejected` tier, toned `blocking` rather than `attention`: `check`
means the system does not know, and a rejection means a person does. The comment
was right about the intent and the code did the opposite, which is the shape this
epic keeps producing — a sentence describing a guarantee that nothing enforces.

While fixing it: `TIER_LABEL`'s "has one for every tier" test enumerated the four
tiers by hand, so it went on passing after a fifth was added. It derives the list
from `TIER_LABEL`'s own keys now, which `Record<FieldTier, string>` makes complete.

### A30c — `isTypingTarget` was never going to cover the editor's buttons

The input guard is right and it is not sufficient. It excludes `INPUT`,
`TEXTAREA`, `SELECT` and `contentEditable` — a `<button>` is none of those, and
correctly so. But the verdict editor is inline, the global listener stayed live
behind it, and focus lands on its buttons: **`Enter` on Cancel activated the button
AND fired `accept`**, recording an acceptance on the very field someone had opened
in order to reject. `Tab` was quieter and worse — the hook calls `preventDefault`
on it, so a keyboard user could not tab from the note field to Save at all.

The shortcut sheet was already handled with `!helpOpen`. The editor is the same
situation and was missed because it is not a dialog. `shortcutsEnabled({ helpOpen,
editing })` now states the rule once, as a named predicate rather than an inline
`&&`, so the part that was wrong is the part that has a test.

### A30d — the drift guard passed because the column's NAME appeared in a predicate

`test_no_model_column_drifts` asked whether a column is "mentioned" in a view's
select list with a `\bname\b` search. The new view drops two columns deliberately
and returns booleans about them: `(corrected_value IS NOT NULL) AS
has_corrected_value`. That contains the string `corrected_value`, so the guard
called the column exposed while the view exposes only whether it is null — and the
decision to drop it went unrecorded in `EXCLUDED`, which is where this file's
posture says decisions live.

The guard now reduces each select item to the name it comes out as. Tightening it
surfaced exactly those two columns and nothing else, so no other view was leaning
on the loophole.

### A30e — `is_sensitive` was still not asking the list that knew

A29 is right, and the check confirms it: `_PII_FIELDS` in
`verification/snapshot/documents_section.py` classifies **83** field names by
`PiiKind`, and `is_sensitive` consulted only the 27 in `critical.identity`. Among
the 56 it did not ask about: `aba_routing_number` and `account_number` — a routing
number beside an account number, which together are enough to originate a debit —
both rendering in the clear in the reviewer's fields pane.

This is A27a's lesson recurring one level up. There, a guard missed a *spelling*.
Here, a guard missed an entire *list that already existed*, and the fix I wrote for
A27 authored a new one beside it rather than deriving from it. Two definitions of
"identifier", and the newer one was narrower.

`is_sensitive` now answers from both, and the default is MASK.

**But not everything in that registry should be masked on a processor's screen,
and getting this wrong in the other direction is also a bug.** `_PII_FIELDS` has
exactly two kinds — `ssn` (19) and `account` (64) — and `account` is too coarse to
drive a display: it holds `aba_routing_number` and `loan_number` alike. The
registry is calibrated for a different question ("may this reach an LLM snapshot
or an analytics view?") than the screen asks ("may the person working this file
read it?"). A first pass at this fix masked the loan number, which a processor
needs on every document.

So there are two written exception lists and they answer different questions.
`critical.identity_readable` is critical AND shown — a date of birth, an EIN, a
licence number, each one a thing a processor VERIFIES. Top-level `pii_readable` is
shown and not critical — a loan number, a policy number, a parcel number. Keeping
the second out of `critical:` matters: listing a loan number there would put a
mark beside every one of them, and a mark on every row is a mark on no row.

Masking stays the default, every exception is a name somebody wrote down, and
`test_nothing_shaped_like_a_money_or_identity_document_is_declared_readable` locks
the escape hatch — an account number, a routing number, a card, a wire reference
or an identity document cannot be argued onto the readable side.
`tax_bill_or_account_number` is deliberately masked on that principle: it reads as
an account number, and a value that has to be argued about belongs on the masked
side.
