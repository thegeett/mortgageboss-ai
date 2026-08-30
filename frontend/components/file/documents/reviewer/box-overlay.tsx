"use client";

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
            key={`${box.field_key}-${box.x0}-${box.y0}`}
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
