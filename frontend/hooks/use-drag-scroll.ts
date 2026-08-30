"use client";

import { type RefObject, useCallback, useEffect, useRef, useState } from "react";

/** How far the pointer may travel before a drag stops counting as a click, in CSS pixels. */
const DRAG_THRESHOLD_PX = 4;

interface DragScroll<T extends HTMLElement> {
  ref: RefObject<T | null>;
  /** Cursor classes — `grab` only while there is something to scroll, `grabbing` while dragging. */
  className: string;
}

/**
 * Click-and-drag horizontal scrolling, with a grab cursor.
 *
 * WHY A HOOK AND NOT A CLASS ON THE ELEMENT. The cursor is the easy half; the hard half is that these
 * strips are made of LINKS AND BUTTONS, and a drag that ends on a tab would otherwise navigate. The
 * pointer travel is measured and a click that follows a real drag is swallowed in the capture phase,
 * before it reaches the tab.
 *
 * THE CURSOR ONLY APPEARS WHEN IT IS TRUE. A grab cursor on a strip that fits its container promises
 * something that does nothing, so overflow is measured and re-measured on resize. That is also why
 * this is not simply `cursor-grab` in the className — the affordance has to track the content.
 *
 * TOUCH AND NON-PRIMARY BUTTONS ARE LEFT ALONE. A touchscreen already pans natively and hijacking it
 * would fight the platform; a middle or right button is not a drag.
 */
export function useDragScroll<T extends HTMLElement>(): DragScroll<T> {
  const ref = useRef<T | null>(null);
  const [scrollable, setScrollable] = useState(false);
  const [dragging, setDragging] = useState(false);
  // Not state: these change on every pointermove and must not re-render the strip mid-drag.
  const origin = useRef<{ x: number; scrollLeft: number } | null>(null);
  const moved = useRef(false);

  const measure = useCallback(() => {
    const el = ref.current;
    if (el) setScrollable(el.scrollWidth > el.clientWidth);
  }, []);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    measure();
    // GUARDED, not assumed. `ResizeObserver` is absent in jsdom and in older engines, and an
    // unguarded `new ResizeObserver` here threw during render — taking 73 component tests with it,
    // in two suites that have nothing to do with scrolling. A strip whose size never changes after
    // mount still gets the single measure above, so the degraded path is a correct cursor that
    // simply stops tracking resize.
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    // The children are what overflow, so a tab appearing or its label changing has to re-measure too.
    for (const child of Array.from(el.children)) observer.observe(child);
    return () => observer.disconnect();
  }, [measure]);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    const onPointerDown = (event: PointerEvent) => {
      if (event.pointerType === "touch" || event.button !== 0) return;
      if (el.scrollWidth <= el.clientWidth) return;
      origin.current = { x: event.clientX, scrollLeft: el.scrollLeft };
      moved.current = false;
      setDragging(true);
    };

    const onPointerMove = (event: PointerEvent) => {
      const start = origin.current;
      if (!start) return;
      const dx = event.clientX - start.x;
      if (Math.abs(dx) > DRAG_THRESHOLD_PX) {
        moved.current = true;
        // Claim the pointer only once it is really a drag, so a plain click on a tab is untouched.
        if (!el.hasPointerCapture(event.pointerId)) el.setPointerCapture(event.pointerId);
      }
      if (moved.current) el.scrollLeft = start.scrollLeft - dx;
    };

    const endDrag = (event: PointerEvent) => {
      if (el.hasPointerCapture(event.pointerId)) el.releasePointerCapture(event.pointerId);
      origin.current = null;
      setDragging(false);
    };

    // CAPTURE PHASE, and this is the whole reason the hook exists: the click has to be swallowed
    // before it reaches the tab underneath. `moved` is cleared here rather than in `endDrag`, because
    // the click arrives AFTER pointerup and would otherwise find the flag already reset.
    const onClickCapture = (event: MouseEvent) => {
      if (!moved.current) return;
      event.preventDefault();
      event.stopPropagation();
      moved.current = false;
    };

    el.addEventListener("pointerdown", onPointerDown);
    el.addEventListener("pointermove", onPointerMove);
    el.addEventListener("pointerup", endDrag);
    el.addEventListener("pointercancel", endDrag);
    el.addEventListener("click", onClickCapture, true);
    return () => {
      el.removeEventListener("pointerdown", onPointerDown);
      el.removeEventListener("pointermove", onPointerMove);
      el.removeEventListener("pointerup", endDrag);
      el.removeEventListener("pointercancel", endDrag);
      el.removeEventListener("click", onClickCapture, true);
    };
  }, []);

  return {
    ref,
    className: scrollable ? (dragging ? "cursor-grabbing select-none" : "cursor-grab") : "",
  };
}
