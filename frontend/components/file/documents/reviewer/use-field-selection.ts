"use client";

import { useCallback, useRef, useState } from "react";

/**
 * Which field is selected, and what a click on the document does (LP-UI-031).
 *
 * THE GUARDRAIL, and it is the reason this is a hook rather than two `useState`
 * calls in a component. If a field is selected and the processor clicks a
 * *different* value on the page, the obvious implementation writes that value
 * into the selected field — because "click the document to fill the field" is
 * how the pattern usually works. That is the single most common destructive
 * misclick in this interaction: a correct income figure silently replaced by an
 * employer's name, on a compliance file, with no undo the processor knows about.
 *
 * So clicking a box belonging to another field NAVIGATES to that field. Filling
 * happens only from the field's own editor. `clickBox` returns what it did, so a
 * caller can tell the two apart without inferring it from the state afterwards.
 */

export type BoxClick =
  | { kind: "selected"; fieldKey: string }
  | { kind: "navigated"; from: string; to: string }
  | { kind: "reselected"; fieldKey: string };

export interface FieldSelection {
  selected: string | null;
  hovered: string | null;
  select: (fieldKey: string | null) => void;
  hover: (fieldKey: string | null) => void;
  /** A click on a box in the page. Never writes a value — see the guardrail. */
  clickBox: (fieldKey: string) => BoxClick;
}

export function useFieldSelection(): FieldSelection {
  const [selected, setSelectedState] = useState<string | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);

  // A ref beside the state, because `clickBox` has to REPORT what it did in the
  // same tick it does it. Deciding inside a `setSelected` updater looks tidier
  // and does not work: the updater runs after the call returns, so the outcome
  // was computed against a value not yet read and every click reported
  // "selected". A caller acting on that — announcing a navigation, moving focus
  // — would act on the wrong one. Caught by the test, not by reading it.
  const current = useRef<string | null>(null);

  const select = useCallback((fieldKey: string | null) => {
    current.current = fieldKey;
    setSelectedState(fieldKey);
  }, []);

  const clickBox = useCallback(
    (fieldKey: string): BoxClick => {
      const previous = current.current;
      select(fieldKey);
      if (previous === null) return { kind: "selected", fieldKey };
      // Clicking the selected field's own box is not a navigation — it is the
      // processor confirming they are looking at the right thing.
      if (previous === fieldKey) return { kind: "reselected", fieldKey };
      return { kind: "navigated", from: previous, to: fieldKey };
    },
    [select],
  );

  return { selected, hovered, select, hover: setHovered, clickBox };
}
