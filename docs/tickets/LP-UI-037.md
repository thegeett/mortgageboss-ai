# LP-UI-037 — Narrow-width pass

Epic F, and the last buildable ticket in the plan — Epic G (038–040) is designed
ahead for Phase 4+ and is explicitly "build when the phase lands, not before".

## The measurement disagreed with the ticket, twice

**Horizontal overflow is zero** at 1280 and at 1024 on every route, verified with
a probe that plants a 3000px element and fails loudly if it does not detect it.
So the first AC already passed before this ticket.

**And the screen was still wrong.** At 1280 the reviewer showed *six* vertical
bands — icon rail, file nav, document list, page canvas, fields pane, context
rail — squeezing the page canvas, the thing being read, to about 550px while the
context rail spent 450 on loan facts nobody needs while reading a pay stub.

Then the sharper one. The rail is `hidden xl:block`, so below 1280 it did not
collapse — it **vanished**, taking the file's status, its three ratios and its
activity with it, and offering nothing to open. A 13-inch laptop is 1280 logical
pixels at its widest common setting and fewer at any scaling above 100%, so that
was the ordinary case rather than an edge one.

## What was built

**`FileContextDrawer`** — the same content, reached from a button in the file
header, shown only where the rail is hidden. Verified live: at 1180 the rail is
absent and the trigger opens the drawer; at 1440 the rail is present and the
trigger is hidden. Reachable at every width, duplicated at none.

Both render `ContextSections`. A rail and a drawer holding separate copies of
"what file context means" is the failure this epic has found in three other
places, and one of them shipped.

**A recorded column ladder.** All nine pipeline columns used to render at every
width and simply got narrower until the addresses were three words and an
ellipsis. Truncating everything equally is a decision too — it is just one nobody
made, and it degrades the columns a processor triages on at the same rate as the
ones they do not.

The order is data in `COLUMNS`, ranked by what triage needs:

| width | columns |
|---|---|
| 1536 | all nine |
| 1280 | drops Touched |
| 1100 | drops Property, Lender |
| 900 | drops Amount, Needs |

**File, Borrower, Stage and Attention are never dropped** — what it is, who it
is, where it is, and whether it needs me. Measured at each width; overflow stays
zero throughout.

## The guard that did not guard, again

`columnClass` returns a literal string per breakpoint. My first test asserted the
returned value — and an interpolated `` `hidden ${bp}:table-cell` `` returns
**exactly the same string** and passes it, while Tailwind, which reads the file
rather than running it, never emits the class. Every column would render at every
width with the suite green.

The check now reads the source text, because that is where the failure lives.
Fourth time in this epic that the authored part of a guard was the part that
failed: which directories, which spellings, which syntaxes, and now which layer.

## The reviewer does not stack, and that is the finding

The ticket proposed it. Once the rail collapses, the three panes have **more room
at 1100** than they had at 1280 with the rail in place — the screenshot is
unambiguous. Stacking would cost the side-by-side comparison that is the
reviewer's entire purpose, to solve a problem the drawer already solved.

The proposal was a reasonable guess about what would be needed. The measurement
disagreed with it, and the measurement is the thing that has been right all
epic.

## The tablet decision

ADR-394. Three commitments in descending confidence: **1280+ is designed**;
**1024–1280, a landscape tablet, is supported** — nothing unreachable, panes stay
side by side; **below 1024 is neither designed nor blocked** — it does not
overflow and it does not lie, and that is the whole claim. A processor assembling
a loan file reads a document beside its extracted values, and two things side by
side is the product.

The consequence is stated there too: someone will eventually report a narrow
width as broken, and the honest answer is out of scope rather than bug.

## Tests

`components/dashboard/column-priority.test.ts` (8) — the four that never drop,
the order of the rest, no phone breakpoint claimed, a class for every breakpoint
named, and the source-text check above.

Mutation-checked, 5 mutations, all caught: Attention made droppable, the order
reshuffled, the class interpolated, a breakpoint with no case falling through to
no class, and a phone breakpoint claimed.

Verified live at 1536 / 1280 / 1180 / 1100 / 900. CI green by exit code: biome,
tsc, 948 vitest. No backend changes.

## Not done

**No test covers the drawer/rail mutual exclusion.** It is verified live at two
widths, but the thing that guarantees it — `xl:hidden` on the trigger against
`hidden xl:block` on the rail — is a pair of classes in two files, and jsdom has
no viewport to evaluate them against. The pairing is the kind that drifts.

---

## Review (LP-UI-037 review commit)

Reviewed on request from the session running the epic. Two fixes, one sweep clean,
one claim narrowed. Staged narrowly — `SPEC.md` is modified by neither of us and
is left alone.

### 1. The drawer/rail pairing is now one definition, and it is tested

The guarantee is that the two classes are COMPLEMENTS: the context reachable at
every width, duplicated at none. Written as two independent strings, that is an
agreement nothing checks — and the failure the ticket names (both `xl:hidden`,
context unreachable above 1280) is invisible to jsdom, which has no viewport.

`RAIL_ONLY` and `DRAWER_ONLY` are defined together and used at both sites, and the
test asserts they name the same breakpoint in opposite directions, plus that each
rendered element carries its half. Three mutations, all caught: both halves hidden
above `xl`, the two on different breakpoints, and a site dropping the constant.

Literal strings, deliberately — the constants are scannable source text, which the
next finding is about.

### 2. The column ladder is read, not restated

The header and the skeleton both map `COLUMNS` and cannot drift. The body cells
restated the breakpoint — `columnClass("xl")` beside `aria-colindex={3}` — so the
ladder was written twice and the two agreed with nothing making them agree.

All nine were correct; the script that applied them did not miss one. But moving a
column's `hideBelow` would have moved the header and the skeleton and left the
body behind, giving a row a column its header had dropped. The body cells call
`columnClassAt(n)` now, reading `COLUMNS` by the index already on the cell.

**And the test compares the rendered header to the rendered body** at each
`aria-colindex`, which is the comparison the guarantee is about — reading `COLUMNS`
and the source cannot see a mismatch between two rendered cells. Demonstrated
against the pre-refactor arrangement: restore one hardcoded `columnClass("2xl")`,
move `COLUMNS` to `lg`, and it fails on column 9.

*Worth recording:* my first attempt at this refactor was a scripted positional
edit that matched the wrong cell — the exact failure the ticket warned about. The
test above is what caught it, which is the argument for writing it.

### 3. Nothing else builds a Tailwind class from a variable

Swept three ways: `className` template literals, `+` concatenation, and any
interpolation appearing mid-class. Every hit is either a whole class name
substituted by a ternary (safe — both literals are in the source), a DOM id, or
the docstring in `attention-cell.tsx` that explains why the pattern is banned. No
live instance.

### 4. ADR-394's band claim is narrowed to its evidence

Nothing structural contradicts "1024–1280 is supported": the largest fixed content
min-width in the tree is 8rem, the reviewer's pane minimum is a percentage rather
than a pixel count, and the column ladder drops four of nine pipeline columns
before 1280 — leaving ~724px of content at 1024 after the icon rail, the nav
column and the shell padding.

But arithmetic is not a reading of the screen, and the conditions, needs,
communication, lender-package and admin screens were never visited in that band.
The ADR now says which two screens the claim rests on and states that the
correction, if one is needed, is to narrow the claim rather than patch the screen.
That is the ticket's own instruction, written into the ADR so it survives the
ticket.

### Verification

biome 0, tsc 0, **952 vitest**, build clean. No backend change, so no pytest run.
Six mutations, all caught.
