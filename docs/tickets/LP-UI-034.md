# LP-UI-034 — Loading, empty and error states

Epic F. Skeletons that don't shift, three distinct empty states, and errors that
name what failed and the way out.

## What the mockup asks for that the ticket text does not

`15-states.png` is more specific than the ticket, and the specifics are the work:

- The filtered-empty state names **the actual filter, the actual query, and the
  count that would come back** — *"Nothing in Blocked to submit matches 'ellis'.
  Clear the search to see all four."* Not "no results".
- The section error names **the cause and the blast radius** — *"Couldn't load the
  borrowers. The request timed out. The rest of the file loaded fine."* A
  processor's next question after any failure is how much of the screen they can
  still trust.
- The whole-page error offers **two** actions: try again, and somewhere to go.
- Structural empty has **no** action.

## The error work: one constant produced the banned phrase everywhere

"Something went wrong" appeared in eight places, and the root was
`GENERIC_MESSAGE` in `lib/errors/api-error.ts` — the fallback every unlabelled
API failure resolved to. Two call sites then **string-compared against it** to
replace it with something better, which is a coupling that breaks silently the
moment the wording changes. This ticket changes the wording.

So: the fallback now says what is known, what is not, and what is safe to assume —
*"The request didn't complete, and nothing was saved. Try again."* — and
`NormalizedError` carries **`isGeneric`**, so a caller can tell whether it is
overriding a real server message or filling a blank without matching on prose.

`title` and `message` are now **required** on `ErrorState`, and `message` on
`InlineErrorState`. That is the point of the change rather than a side effect: a
required prop means no screen can fall back into an apology. Every production call
site already passed them; only a test broke.

`lib/errors/no-apology.test.ts` scans the source and fails if the phrase returns.
It is block-comment-aware, because a comment explaining why a phrase is banned
legitimately quotes it, and a guard that punished that would push authors into not
explaining themselves.

## The three empty states

`components/ui/empty-state.tsx`. Three kinds, three glyphs, and **`structural`
refuses an action even when one is passed** — enforced in the component rather
than left to each caller, because correct-to-be-empty means there is nothing to
do and a button would say otherwise.

`describeFilter` builds the filtered sentence and degrades honestly: with no
summary it says the general thing rather than inventing a filter name, and it
promises a count only when it has one. "See all four" is a claim, and a wrong one
sends a processor looking for files that are not there. The count costs one extra
request, fired only when a processor is already looking at an empty filtered list.

## The verification tabs are a fourth case, and were left alone

`rule-findings-tabs.tsx` had its own local `EmptyState`. Its states are not this
ticket's three: there, empty is a **verdict** — "Nothing needs attention" is good
news and carries a check glyph, "Nothing to show — and that's by design" is
structural, "Nothing has stopped applying" is neither. The caller chooses the
glyph because the glyph *is* the finding, which the shared primitive deliberately
does not allow.

Renamed to `OutcomeEmpty`. Two components with one name meaning two different
things is how the wrong one gets reached for; the copy is unchanged.

## The layout shift, measured rather than assumed

Injected 1.5s of latency and polled the DOM for the first skeleton frame and the
first real frame, comparing row heights.

| surface | before | after |
|---|---|---|
| pipeline table | **0px** | 0px (already correct) |
| documents list | **25px** | 2px |

The documents skeleton was a stack of `h-[58px]` bars while the rows had become
53px — a hardcoded height is a copy of a number that lives somewhere else, and it
rots silently because nothing renders both and compares. Rebuilt from the same
table primitives, mirroring the real first cell's **two lines** (the standard name
and the gist), which is what makes that row 53px rather than 28px. `h-5`/`h-4` are
the line heights of `text-sm`/`text-xs`, not guesses.

The residual 2px is the row border. The remaining honest gap is **row count**: the
skeleton shows three rows and the real list showed nine, so content below still
moves. A skeleton cannot know how many rows will arrive, and the mockup's own
loading example shows three rows rather than a full page, so this is recorded
rather than papered over.

Extracting `DOCUMENT_COLUMNS` removed the header duplication the rebuild would
otherwise have created, and `list-skeleton.test.tsx` asserts the skeleton renders
one cell per real column — a new column reaching the rows and not the skeleton
reads as a column jumping sideways.

## Tests

`empty-state.test.tsx` (4), `describe-filter.test.ts` (6),
`list-skeleton.test.tsx` (5), `no-apology.test.ts` (3), plus `isGeneric` coverage
in `api-error.test.ts`.

Mutation-checked, 14 mutations, all caught: the banned phrase returning in the
shared fallback and in the boundary, `isGeneric` stuck true/false and ignoring the
legacy `detail` shape, the scanner treating every line as a comment or reading no
files, a structural state offering an action, all three kinds sharing a glyph, the
skeleton losing a cell, the first cell back to one line, a hardcoded pixel height
returning, the filtered sentence dropping the query, and a count promised when
there is none.

Checked in light and dark. CI green by exit code: biome, tsc, 892 vitest.

## Not done in this ticket

`ErrorBoundary`'s fallback was rewritten to name what failed and what is safe
("This screen stopped working" / "Nothing you have entered has been sent or
changed"), but it is not a pixel match to the mockup's whole-page error — the
mockup's version is file-scoped ("This file wouldn't open", "Back to the
pipeline") and the boundary is global, so its way out cannot be a file route. The
shared `ErrorState` now supports the two-action shape the mockup shows, and
`file-error.tsx` is the screen that matches it.

The other 20 or so ad-hoc empty states outside the lists named here still render
their own markup. They read correctly; they simply do not use the primitive yet.

---

## Review (LP-UI-034 review commit)

Reviewed on request from the session running the epic. Four findings, three of
them in the guards rather than in the feature.

### 1. The ban guard did not scan `hooks/`

`SEARCH` listed `["app", "components", "lib"]`. `hooks/` holds six files including
`use-require-auth` — exactly the kind of place a toast message gets written.
Verified by planting "Something went wrong" there: the whole suite stayed green.

A scan that does not look somewhere is indistinguishable from one that looks and
finds nothing, and this guard exists for the file nobody has written yet. The
roots are derived from the tree now, so a new top-level source directory cannot be
missed by being forgotten.

### 2. `codeLines` dropped code that shared a line with a comment

A line opening a block comment was skipped whole, so
`/* note */ const m = "Something went wrong";` — a line a formatter can produce —
was read as a comment and reported nothing. It strips the commented spans now and
keeps the rest, which also preserves the property the function exists for: a
comment quoting the banned phrase to explain the ban is still skipped.

### 3. The skeleton had no group heading, and that is where the shift is

The per-row work is right — the skeleton is built from the same primitives, so it
cannot drift from the row height again. But the loaded list **always** renders a
category label and a count pill above each table, and the skeleton rendered a bare
table. The rows arrive lower than they started on every documents tab, and no
per-row fix can reach it, because it is above the rows.

This is worth weighing against the measurement. 2px is not consistent with a
missing heading line; a group label plus its margin is an order of magnitude more
than that. The likely explanation is what the ticket already worried about — the
polled element. Measuring the container's top rather than the first row's would
report a small number while the rows moved. The skeleton now renders the heading,
with the `h3` and pill keeping their own classes so the line box comes from the
type scale rather than a height typed in by hand.

### 4. `DOCUMENT_COLUMNS` keeps the header and the skeleton in step, not the rows

Both the header and the skeleton map the shared list. The real row hand-writes its
five cells. So adding a sixth column grows the header and the skeleton and leaves
the row behind — which is precisely the sideways jump the comment on that list
describes as the thing it prevents. `list-skeleton.test.tsx` pinned skeleton
against columns and never rendered a real row. `DocumentRow` is exported and the
comparison is made against the existing `doc()` factory; verified by adding a
sixth column, which now fails.

### Confirmed, not changed

- **The row COUNT (3 vs 9).** The judgement holds, and it is checkable rather than
  a matter of taste: no document count exists on any response the page already
  has — not on the loan-file detail, not anywhere in the document types. On a cold
  load the client genuinely cannot know how many rows are coming.
- **The `isGeneric` refactor.** No stale string comparison survives anywhere; the
  remaining occurrences of the banned phrases are all inside comments explaining
  the ban, which the fixed `codeLines` correctly skips.
- **The remaining ad-hoc empty states.** Measured: 23 files carry a `length === 0`
  branch without the primitive, matching the ticket's estimate. Several are
  conditional guards rather than empty states. None of them say a banned phrase,
  and the fixed guard now covers all of them.

### Verification

biome 0, tsc 0, **898 vitest**, build clean. No backend change, so no pytest run.
Six mutations, all caught.
