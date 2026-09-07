"use client";

import { useEffect, useRef } from "react";

import type { FieldBox } from "@/lib/api/field-boxes";
import { cn } from "@/lib/utils";

/**
 * The highlight boxes over a rendered page (LP-UI-031).
 *
 * Coordinates are normalised 0..1, so the overlay is a percentage box over the
 * image and needs to know nothing about the zoom it was rendered at.
 *
 * Three states, and the quiet one matters most: an unselected box shows only
 * while `showAll` is held (Alt), because forty faint rectangles over a pay stub
 * is not a document any more. The selected field's box is always visible; a
 * hovered one is emphasised.
 *
 * A box is a BUTTON, not a div with a click handler — a processor reviewing a
 * document with the keyboard (LP-UI-033) has to be able to reach it, and the
 * accessible name is the field it belongs to rather than the text underneath,
 * which would put borrower content into the accessibility tree twice.
 */
/**
 * A 0..1 coordinate as a CSS percentage.
 *
 * Rounded, because floating point turns `(0.25 - 0.2) * 100` into
 * `4.999999999999999%` — harmless to render, unreadable in the DOM, and it makes
 * two identical boxes compare as different. Four decimals is well past a pixel on
 * any page we render.
 */
function pct(value: number): string {
  return `${Math.round(value * 1_000_000) / 10_000}%`;
}

/**
 * One box's identity, for React's key AND for deciding which box holds the ref.
 *
 * Written out twice these drift, and the drift is silent: the ref would attach to
 * a box the effect is not watching, so the scroll would simply not happen.
 */
function boxKey(box: FieldBox): string {
  return `${box.field_key}-${box.x0}-${box.y0}`;
}

export function BoxOverlay({
  boxes,
  page,
  selected,
  hovered,
  showAll,
  onSelect,
  onHover,
  labelFor,
}: {
  boxes: FieldBox[];
  page: number;
  selected: string | null;
  hovered: string | null;
  /** Alt held — reveal every other candidate the extraction found. */
  showAll: boolean;
  onSelect: (fieldKey: string) => void;
  onHover: (fieldKey: string | null) => void;
  labelFor: (fieldKey: string) => string;
}) {
  const onThisPage = boxes.filter((box) => box.page === page);

  // BRING THE SELECTED BOX INTO VIEW. Selecting a field already jumped to the
  // box's PAGE, and that was the whole of it — so on a zoomed page, where the pan
  // region scrolls, selecting a field highlighted a rectangle somewhere outside
  // the visible area and the screen appeared not to respond. The fields pane has
  // had the mirror of this since LP-UI-030 (`selectedRow.scrollIntoView`); the
  // document side never did.
  //
  // KEYED ON THE BOX, NOT ON `selected`, and that is the whole of this fix rather
  // than a tidying of it. Keyed on the selection alone, the effect ran in the
  // commit where the selection changed — which for a box on ANOTHER page is a
  // commit where that box is not rendered and the ref is null. The page follows
  // in a LATER commit (`review/page.tsx` moves it from an effect), by which time
  // the selection has not changed and the effect does not run again. So the case
  // this was reported for — the box is on page 3, the processor is on page 1 —
  // scrolled nowhere, and only a box already on the page on screen ever worked.
  // The same shape hides a second one: the boxes arrive from a query, so
  // selecting a field before they load also ran the effect against a null ref.
  //
  // The identity below changes when the box APPEARS, however it appears, so both
  // commits are covered by one dependency and neither needs an ordering
  // assumption. Hover is not in it, so skimming still never scrolls.
  //
  // THE FIRST BOX, not whichever React attached last. A field can have several
  // boxes on one page — the matcher returns up to `MAX_MATCHES` — and giving them
  // all the same ref left `current` holding the last one to mount, so the page
  // scrolled to the bottom-most occurrence by accident rather than to the first
  // one a reader would look for.
  //
  // `block: "nearest"` so a box already on screen does not move: a processor who
  // clicked a box must not have the page jump out from under the click.
  const target = selected ? onThisPage.find((box) => box.field_key === selected) : undefined;
  const targetKey = target ? boxKey(target) : null;
  const selectedBox = useRef<HTMLButtonElement | null>(null);
  useEffect(() => {
    if (!targetKey) return;
    selectedBox.current?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [targetKey]);

  if (onThisPage.length === 0) return null;

  return (
    // `inset-0` over the image's own box; `pointer-events-none` so the wrapper
    // never eats a scroll, with each box opting back in.
    <div className="pointer-events-none absolute inset-0">
      {onThisPage.map((box) => {
        const isSelected = box.field_key === selected;
        const isHovered = box.field_key === hovered;
        const visible = isSelected || isHovered || showAll;
        return (
          <button
            key={boxKey(box)}
            ref={boxKey(box) === targetKey ? selectedBox : undefined}
            type="button"
            aria-label={`Highlight for ${labelFor(box.field_key)}`}
            aria-pressed={isSelected}
            onClick={() => onSelect(box.field_key)}
            onMouseEnter={() => onHover(box.field_key)}
            onMouseLeave={() => onHover(null)}
            onFocus={() => onHover(box.field_key)}
            onBlur={() => onHover(null)}
            style={{
              left: pct(box.x0),
              top: pct(box.y0),
              width: pct(box.x1 - box.x0),
              height: pct(box.y1 - box.y0),
            }}
            // OUTLINE, NOT BORDER, and offset outwards. A box is the text's own
            // bounding rectangle — on a pay stub that is about ten pixels tall,
            // and a 2px border drawn inside it covers the very word the box is
            // pointing at. An outline sits outside the rectangle and leaves the
            // glyphs legible, which is the whole point of highlighting them.
            className={cn(
              // `[outline-style:solid]`, not the bare `outline` utility:
              // tailwind-merge groups `outline` (style) with `outline-1` (width)
              // and drops the earlier one, leaving `outline-style: none` and a
              // ring that never draws. An arbitrary property is in no group.
              "pointer-events-auto absolute rounded-[1px] outline-offset-1 [outline-style:solid] transition-opacity",
              isSelected
                ? "bg-primary/20 outline-2 outline-primary"
                : isHovered
                  ? "bg-primary/10 outline-1 outline-primary/70"
                  : "outline-1 outline-primary/40",
              visible ? "opacity-100" : "opacity-0",
            )}
          />
        );
      })}
    </div>
  );
}
