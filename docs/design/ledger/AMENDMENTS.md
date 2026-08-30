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

---

## Standing note

The design assets are **not** infallible. LP-UI-001 found two real defects in them
by verifying rather than trusting, which is exactly right. Keep doing that: if a
ticket's premise does not survive contact with the code, say so on the ticket
rather than working around it, and the asset gets corrected here.

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
