"use client";

import { type RefObject, useCallback, useEffect, useRef, useState } from "react";

/**
 * Drag the page to move around it when it does not fit (LP-UI-043).
 *
 * A zoomed page overflows its pane and the pane scrolls — it always did. What it
 * did not do was SAY so: the cursor stayed `auto`, the wheel only moved one axis,
 * and the arrow keys were claimed by the reviewer's field navigation. So a
 * processor who zoomed in to read a figure had a page they could see the middle
 * of and no obvious way to reach the edges.
 *
 * Grab-and-drag is what every document viewer does, and it is the one gesture
 * that moves both axes at once.
 *
 * ONLY WHEN THERE IS SOMEWHERE TO GO. At fit the page does not overflow, and a
 * grab cursor over a page that cannot move is a promise the screen does not keep.
 */

/** Movement beyond this is a drag; below it the pointer was held still and clicked. */
const DRAG_THRESHOLD_PX = 3;

export interface Pan {
  /** True when the content overflows in either axis. */
  pannable: boolean;
  /** True while a drag is in progress. */
  panning: boolean;
  onPointerDown: (event: React.PointerEvent<HTMLElement>) => void;
}

export function usePan(ref: RefObject<HTMLElement | null>): Pan {
  const [pannable, setPannable] = useState(false);
  const [panning, setPanning] = useState(false);

  // Whether the pointer travelled far enough to be a drag. Read by the capture
  // listener below, which has to answer in the same tick the click arrives.
  const dragged = useRef(false);

  // Re-measure whenever the element resizes OR its content does — a zoom change
  // is a content resize, and so is the pane divider moving.
  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const measure = () =>
      setPannable(
        element.scrollWidth > element.clientWidth || element.scrollHeight > element.clientHeight,
      );
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    for (const child of Array.from(element.children)) observer.observe(child);
    return () => observer.disconnect();
  });

  /**
   * Swallow the click that ends a drag.
   *
   * The highlight boxes are buttons (LP-UI-031), so a drag that starts on one
   * would otherwise select that field on release — the processor moved the page
   * and the app navigated. Capture phase, because the button's own handler runs
   * in the bubble phase and would already have fired.
   */
  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const swallow = (event: MouseEvent) => {
      if (!dragged.current) return;
      dragged.current = false;
      event.stopPropagation();
      event.preventDefault();
    };
    element.addEventListener("click", swallow, true);
    return () => element.removeEventListener("click", swallow, true);
  }, [ref]);

  const onPointerDown = useCallback(
    (event: React.PointerEvent<HTMLElement>) => {
      const element = ref.current;
      // Left button only: a right-click is a context menu and a middle-click is
      // the browser's own autoscroll.
      if (!element || event.button !== 0) return;
      if (
        element.scrollWidth <= element.clientWidth &&
        element.scrollHeight <= element.clientHeight
      )
        return;

      const startX = event.clientX;
      const startY = event.clientY;
      const startLeft = element.scrollLeft;
      const startTop = element.scrollTop;
      dragged.current = false;
      setPanning(true);

      const move = (moveEvent: PointerEvent) => {
        const dx = moveEvent.clientX - startX;
        const dy = moveEvent.clientY - startY;
        if (Math.abs(dx) > DRAG_THRESHOLD_PX || Math.abs(dy) > DRAG_THRESHOLD_PX) {
          dragged.current = true;
        }
        // Move the CONTENT with the hand: dragging left reveals what is right of
        // the viewport, which is the direction every document viewer uses.
        element.scrollLeft = startLeft - dx;
        element.scrollTop = startTop - dy;
      };
      const up = () => {
        setPanning(false);
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", up);
        window.removeEventListener("pointercancel", up);
      };
      // On WINDOW, not the element: a pointer that leaves the pane mid-drag must
      // keep panning, and must still end the drag when it is released outside.
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", up);
      window.addEventListener("pointercancel", up);
    },
    [ref],
  );

  return { pannable, panning, onPointerDown };
}
