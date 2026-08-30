# LP-UI-043 — Move around a zoomed page

Reported from the running app: at zoom you could not move around the page, with a
proposal — a hand cursor and drag-to-scroll. Both halves of the report were right.

## What was actually wrong

Measured before changing anything. At 200% the pane **could** scroll — 988px of
content in 506px, both axes — so scrollbars existed. Three things made it feel
like it could not:

- **No affordance.** `cursor: auto` over a page that moves.
- **The wheel does one axis.** Vertical only, which is half of what a zoomed page
  needs.
- **The arrow keys were mine.** LP-UI-033 bound `ArrowUp`/`ArrowDown` to field
  navigation with `preventDefault`, and `Space` to the overlay toggle. Measured:
  `ArrowRight` moved the pane by `0`.

So the scrolling worked and nothing said so or reached it.

## Drag to pan

`usePan` — pointer down anywhere on the page view, drag, the content follows the
hand. `grab` when there is somewhere to go, `grabbing` while going.

**Only when the page overflows.** At fit the cursor stays `auto`: a grab cursor
over a page that cannot move is a promise the screen does not keep.

**The listeners are on `window`, not the element.** A pointer that leaves the
pane mid-drag has to keep panning, and has to end the drag when it is released
outside — a pointer released over the fields pane otherwise leaves the page stuck
to the cursor.

**The click that ends a drag is swallowed.** The highlight boxes are buttons
(LP-UI-031), so dragging from one would otherwise select that field on release —
the processor moves the page and the app navigates. Movement beyond 3px marks it
a drag; a capture-phase listener eats that one click. Below the threshold a real
click still goes through, because clicking a box to select its field is the whole
of LP-UI-031's second direction.

## The bug the instrumentation found

The cursor changed to `grabbing` on press and reverted to `grab` the moment the
pointer moved, while the page still scrolled. The cause: **the browser's native
image drag** fires `pointercancel`, which ended the pan as it started. On a real
mouse that is a page that feels dead under the hand while the cursor claims
otherwise.

`draggable={false}` on the image. Found by instrumenting the drag and reading the
class list at each step — looking at it would have shown a page that moved,
because the scroll had already happened by then.

## And the keyboard half

A page pannable only by dragging is a page unreadable without a mouse, which
would have quietly undone part of LP-UI-036.

The page view is a named `<section>` with `tabIndex={0}`, and the reviewer's key
handler now leaves `ArrowUp`/`Down`/`Left`/`Right` and `Space` alone when focus is
inside `[data-pan-region]`. Everything else still fires there — `Enter`, `E`, `R`,
the brackets — because none of those is how a person scrolls.

The `noNoninteractiveTabindex` suppression carries its reason: a focusable
scrollable region with an accessible name is the WAI-recommended pattern, and the
rule's heuristic (only interactive roles may take focus) does not cover it.

## Tests

`use-pan.test.tsx` (8) — pannable only on overflow, the content moving with the
hand, panning continuing off-pane and ending on release, the left button only,
and both sides of the click threshold. Plus the pan region and `draggable` in
`page-canvas.test.tsx`, and the arrow-key handover in `use-review-keys.test.tsx`.

`vitest.setup.ts` is new: jsdom implements no `ResizeObserver`, which the hook
uses to know whether the page currently overflows. Stubbed in the test
environment rather than guarded in the hook — a `typeof ResizeObserver` check in
application code would make the feature silently do nothing while the tests
passed over a hook that never measured.

Mutation-checked, 8, all caught: the drag-end click selecting a field, a real
click swallowed, the page dragged the wrong way, a fitting page still grabbable,
the drag never ending, a right-click starting one, the image draggable again, and
the arrow keys stolen back.

Verified live at fit and 200%: `auto` → `grab` → `grabbing` → `grab`, a 120px
drag moving the page exactly 120px, and the arrows reaching the pane. CI green by
exit code: biome, tsc, 1003 vitest. No backend changes.

## Not done

**No horizontal wheel or shift-wheel handling** — the browser does shift-wheel
natively over a scrollable box, and trackpad users get both axes already. Adding
our own would be a second implementation of something the platform does.

**No zoom-to-point.** Zooming in keeps the scroll offset rather than holding the
point under the cursor still, so a reader zooming into a corner has to pan back to
it. That is the next thing I would do here if it is worth doing.
