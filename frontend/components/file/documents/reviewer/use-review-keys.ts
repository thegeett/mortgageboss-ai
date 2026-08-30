"use client";

import { useEffect } from "react";

/**
 * The reviewer's keyboard rhythm (LP-UI-033).
 *
 * The ticket's metric is flagged fields per minute, and a processor who has to
 * reach for the mouse between every field will not get there. So the whole loop
 * is bound, and the bindings are single keys — a chord costs a hand position.
 *
 * SHORTCUTS NEVER FIRE WHILE A TEXT INPUT HAS FOCUS. This is not politeness; `E`
 * opens an inline editor and `R` is a rejection, so typing "Rate" into a
 * correction box would reject four fields and open an editor twice. The guard is
 * the first thing this hook does and the reason it is a hook rather than a
 * scattering of `onKeyDown`s.
 */

export interface ReviewKeyActions {
  /** Next field wanting attention. Skips the confident ones — that is the point. */
  nextField: () => void;
  previousField: () => void;
  /** Accept the extracted value. */
  accept: () => void;
  /** Accept and move on in one keystroke — the rhythm the metric is about. */
  acceptAndAdvance: () => void;
  /** Open the inline editor on the focused field. */
  edit: () => void;
  /** Reject / unable to verify. */
  reject: () => void;
  /** Show or hide every highlight box. */
  toggleOverlay: () => void;
  previousDocument: () => void;
  nextDocument: () => void;
  /** Mark the document reviewed and advance the queue. */
  markReviewed: () => void;
  /** Show or hide the shortcut sheet. */
  toggleHelp: () => void;
}

/**
 * Whether a key event came from somewhere the user is typing.
 *
 * `isContentEditable` matters as much as the tag names: a rich-text note is a
 * `div`, and a guard that only knew about `input` would fire every shortcut into
 * one. `readOnly` inputs are NOT excluded — the caret is still there and the
 * shortcut would still feel like a typo.
 */
export function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  const tag = target.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
}

/** Which action a key event asks for, or null. Pure, so the table is testable. */
export function actionFor(event: {
  key: string;
  shiftKey: boolean;
  metaKey: boolean;
  ctrlKey: boolean;
  altKey: boolean;
}): keyof ReviewKeyActions | null {
  const { key, shiftKey, metaKey, ctrlKey, altKey } = event;

  // ⌘Enter first: it is Enter with a modifier, and testing `Enter` earlier would
  // swallow it into `accept`.
  if (key === "Enter" && (metaKey || ctrlKey)) return "markReviewed";
  if (key === "Enter" && shiftKey) return "acceptAndAdvance";
  if (key === "Enter") return "accept";

  // Alt is the box-reveal held modifier (LP-UI-031); a letter with Alt held is a
  // different gesture, not this one.
  if (altKey) return null;
  // Any other modifier means a browser or OS shortcut, not ours.
  if (metaKey || ctrlKey) return null;

  switch (key) {
    case "Tab":
      return shiftKey ? "previousField" : "nextField";
    case "ArrowDown":
      return "nextField";
    case "ArrowUp":
      return "previousField";
    case "e":
    case "E":
      return "edit";
    case "r":
    case "R":
      return "reject";
    case " ":
      return "toggleOverlay";
    case "[":
      return "previousDocument";
    case "]":
      return "nextDocument";
    case "?":
      return "toggleHelp";
    default:
      return null;
  }
}

/** Keys whose default the browser must not also handle when we act on them. */
const PREVENT_DEFAULT = new Set<keyof ReviewKeyActions>([
  // Space scrolls the page, Tab moves focus out of the reviewer, and the arrows
  // scroll the document pane — each would happen ON TOP of our action.
  "toggleOverlay",
  "nextField",
  "previousField",
  "markReviewed",
  "acceptAndAdvance",
]);

export function useReviewKeys(actions: ReviewKeyActions, enabled = true): void {
  useEffect(() => {
    if (!enabled) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (isTypingTarget(event.target)) return;
      const action = actionFor(event);
      if (!action) return;
      if (PREVENT_DEFAULT.has(action)) event.preventDefault();
      actions[action]();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [actions, enabled]);
}
