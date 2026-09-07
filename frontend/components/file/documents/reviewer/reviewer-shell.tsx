"use client";

import { cn } from "@/lib/utils";
import { useCallback, useEffect, useRef, useState } from "react";

/**
 * The reviewer's three resizable panes (LP-UI-030).
 *
 * Document list · page canvas · extracted fields. The dividers are keyboard
 * operable, not only draggable: a processor reviewing forty fields is already on
 * the keyboard (LP-UI-033), and a control that needs a mouse breaks that rhythm.
 *
 * The split is a percentage pair — `[list, canvas]`, fields taking the remainder
 * — so the layout survives a window resize without recomputation. Persisted per
 * user rather than per browser, because it is a working preference like row
 * density; `null` means never adjusted and renders `DEFAULT_SPLIT` rather than
 * writing a value nobody chose.
 *
 * Container queries live on the fields pane (see `reviewer-fields`): its rows
 * reflow to the PANE's width, so the same component works at 320px and 720px
 * without knowing anything about the window.
 */

/** `[list %, canvas %]`. The fields pane takes what is left. */
export type PaneSplit = [number, number];

export const DEFAULT_SPLIT: PaneSplit = [22, 50];

/** Matches the server's validator, which is the thing that actually enforces it. */
const MIN_PANE = 10;
const MAX_TWO = 90;

export function clampSplit([list, canvas]: PaneSplit): PaneSplit {
  const l = Math.max(MIN_PANE, Math.min(list, MAX_TWO - MIN_PANE));
  const c = Math.max(MIN_PANE, Math.min(canvas, MAX_TWO - l));
  return [Math.round(l), Math.round(c)];
}

export function ReviewerShell({
  split,
  onSplitChange,
  list,
  canvas,
  fields,
}: {
  split: PaneSplit | null;
  /** Called when a drag ends or a key moves a divider — not on every frame. */
  onSplitChange: (split: PaneSplit) => void;
  list: React.ReactNode;
  canvas: React.ReactNode;
  fields: React.ReactNode;
}) {
  const container = useRef<HTMLDivElement>(null);
  const [live, setLive] = useState<PaneSplit>(split ?? DEFAULT_SPLIT);
  const dragging = useRef<0 | 1 | null>(null);

  // Follow the server value when it arrives or changes elsewhere, but never
  // while a drag is in flight — that would fight the pointer.
  useEffect(() => {
    if (dragging.current === null && split) setLive(split);
  }, [split]);

  const move = useCallback((clientX: number) => {
    const box = container.current?.getBoundingClientRect();
    if (!box || dragging.current === null) return;
    const pct = ((clientX - box.left) / box.width) * 100;
    setLive((current) =>
      dragging.current === 0
        ? clampSplit([pct, current[1]])
        : clampSplit([current[0], pct - current[0]]),
    );
  }, []);

  useEffect(() => {
    if (dragging.current === null) return;
    const onMove = (event: PointerEvent) => move(event.clientX);
    const onUp = () => {
      dragging.current = null;
      setLive((current) => {
        onSplitChange(current);
        return current;
      });
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
  });

  const nudge = (index: 0 | 1, delta: number) => {
    const next = clampSplit(index === 0 ? [live[0] + delta, live[1]] : [live[0], live[1] + delta]);
    setLive(next);
    onSplitChange(next);
  };

  const [listPct, canvasPct] = live;

  return (
    <div ref={container} className="flex h-full min-h-0 w-full">
      <section
        aria-label="Documents"
        className="min-w-0 overflow-y-auto border-r border-border"
        style={{ width: `${listPct}%` }}
      >
        {list}
      </section>

      <Divider
        label="Resize the document list"
        onStart={() => {
          dragging.current = 0;
        }}
        onNudge={(delta) => nudge(0, delta)}
        value={listPct}
      />

      <section
        aria-label="Page"
        className="min-w-0 overflow-auto bg-muted/40"
        style={{ width: `${canvasPct}%` }}
      >
        {canvas}
      </section>

      <Divider
        label="Resize the page view"
        onStart={() => {
          dragging.current = 1;
        }}
        onNudge={(delta) => nudge(1, delta)}
        value={canvasPct}
      />

      {/* The remainder, so the three always sum to the container exactly —
          giving this one a percentage too would leave a rounding gap. */}
      <section aria-label="Fields" className="min-w-0 flex-1 overflow-y-auto">
        {fields}
      </section>
    </div>
  );
}

/**
 * One divider: a drag target and a keyboard control.
 *
 * `separator` with `aria-valuenow` rather than a bare div — a screen reader
 * announces it as an adjustable thing, and arrow keys move it, so the layout is
 * reachable without a pointer.
 */
function Divider({
  label,
  onStart,
  onNudge,
  value,
}: {
  label: string;
  onStart: () => void;
  onNudge: (delta: number) => void;
  value: number;
}) {
  return (
    <div
      role="separator"
      aria-label={label}
      aria-orientation="vertical"
      aria-valuenow={Math.round(value)}
      aria-valuemin={MIN_PANE}
      aria-valuemax={MAX_TWO}
      tabIndex={0}
      onPointerDown={(event) => {
        event.preventDefault();
        onStart();
      }}
      onKeyDown={(event) => {
        if (event.key === "ArrowLeft") {
          event.preventDefault();
          onNudge(-2);
        } else if (event.key === "ArrowRight") {
          event.preventDefault();
          onNudge(2);
        }
      }}
      className={cn(
        "relative w-1 shrink-0 cursor-col-resize bg-border transition-colors",
        "hover:bg-primary/40 focus-visible:bg-primary",
        // THE HIT AREA IS WIDER THAN THE LINE (WCAG 2.5.8). A 4px strip is a
        // 4px pointer target; the pseudo-element extends the grabbable region to
        // 24px without drawing anything, so the divider stays a hairline and
        // stops being a test of mouse accuracy.
        "before:absolute before:inset-y-0 before:-left-2.5 before:-right-2.5 before:content-['']",
      )}
    />
  );
}
