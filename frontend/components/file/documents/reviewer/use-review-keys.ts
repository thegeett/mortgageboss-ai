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

/**
 * Every action name, as DATA.
 *
 * `shortcut-sheet.test.tsx` asserts the sheet documents every action the reviewer
 * has. It held its own copy of this list, typed `keyof ReviewKeyActions` — which
 * catches a REMOVED action (the literal stops compiling) and misses an ADDED one
 * entirely: the new name is simply absent, and a list that never mentions it
 * cannot notice it. That is the failure the test exists to prevent, one level up.
 *
 * The `satisfies` clause rejects a name here that is not on the interface, and
 * `_everyActionListed` below rejects an interface member that is not here. So the
 * two cannot drift in either direction, and the test enumerates this instead.
 */
export const REVIEW_KEY_ACTIONS = [
  "nextRow",
  "previousRow",
  "nextField",
  "previousField",
  "accept",
  "acceptAndAdvance",
  "edit",
  "reject",
  "toggleOverlay",
  "zoomIn",
  "zoomOut",
  "zoomReset",
  "previousDocument",
  "nextDocument",
  "markReviewed",
  "toggleHelp",
] as const satisfies readonly (keyof ReviewKeyActions)[];

/**
 * Compile-time exhaustiveness: an interface member missing from the list above
 * makes this type `false`, and `true` no longer assigns to it.
 */
type _MissingFromList = Exclude<keyof ReviewKeyActions, (typeof REVIEW_KEY_ACTIONS)[number]>;
const _everyActionListed: [_MissingFromList] extends [never] ? true : false = true;
void _everyActionListed;

export interface ReviewKeyActions {
  /**
   * The next row in the list, in the order the list is drawn (LP-701).
   *
   * Bound to the ARROWS, and separate from `nextField` on purpose. A processor
   * pressing ↓ is reading the list, and a list that answers ↓ by moving four
   * rows and wrapping does not read as a shortcut — it reads as broken.
   */
  nextRow: () => void;
  previousRow: () => void;
  /**
   * Next field wanting attention. Skips the confident ones — that is the point,
   * and Tab is the key that says so in the shortcut sheet.
   */
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
  /** Enlarge / shrink the page, and back to fitting the column. */
  zoomIn: () => void;
  zoomOut: () => void;
  zoomReset: () => void;
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
/**
 * Whether the event came from inside the scrollable page view.
 *
 * The arrow keys belong to that view while it has focus: a zoomed page has to be
 * readable without a mouse, and stealing the arrows for field navigation left it
 * pannable only by dragging. Everything else — Enter, E, R, the brackets — still
 * fires, because none of them is how a person scrolls.
 */
export function isPanRegion(target: EventTarget | null): boolean {
  return target instanceof HTMLElement && target.closest("[data-pan-region]") !== null;
}

/** Keys the page view keeps for itself when it has focus. */
const SCROLL_KEYS = new Set(["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", " "]);

export function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  const tag = target.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
}

/**
 * Whether the reviewer's shortcuts own the keyboard right now.
 *
 * `isTypingTarget` is not enough on its own, and the verdict editor is where that
 * shows. It covers the INPUT the processor types a correction into — but the
 * editor also has buttons, and a `<button>` is not a typing target. With the
 * editor open and focus on Cancel or Save, `Enter` activated the button AND fired
 * `accept`, recording an acceptance on the very field someone had opened in order
 * to REJECT. `Tab` was worse in a quieter way: the hook calls `preventDefault` on
 * it, so a keyboard user could not tab from the note field to Save at all — the
 * selection moved behind the editor instead.
 *
 * So an open overlay takes the keyboard entirely, the same way the shortcut sheet
 * already did. This is a predicate rather than an inline `&&` at the call site so
 * that the rule can be tested, since the rule is the part that was wrong.
 */
export function shortcutsEnabled({
  helpOpen,
  editing,
}: {
  helpOpen: boolean;
  editing: string | null;
}): boolean {
  return !helpOpen && editing === null;
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
    // THE ARROWS STEP ONE ROW. They used to be aliases for Tab, which skips
    // every confident and already-decided field — so on a real pay stub ↓ went
    // 5, 6, 7, 9, … 13, 15, 16 and wrapped to 5, and a confident field draws no
    // mark, so nothing on the screen explained any of it (LP-701).
    case "ArrowDown":
      return "nextRow";
    case "ArrowUp":
      return "previousRow";
    case "e":
    case "E":
      return "edit";
    case "r":
    case "R":
      return "reject";
    case " ":
      return "toggleOverlay";
    // `+` needs no shift on the numeric keypad and `=` is the unshifted key it
    // shares on a full keyboard, so both mean the same thing.
    case "+":
    case "=":
      return "zoomIn";
    case "-":
    case "_":
      return "zoomOut";
    case "0":
      return "zoomReset";
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
  "nextRow",
  "previousRow",
  "markReviewed",
  "acceptAndAdvance",
  // AND PLAIN ENTER. Each field row's label is a `<button>`, so after clicking one
  // it holds focus while the arrows move the SELECTION elsewhere — the normal
  // state since LP-701 made ↓ step one row. Enter then accepted the selected field
  // and the browser's own activation of the still-focused button snapped the
  // selection back to the clicked row. `acceptAndAdvance` was immune only because
  // it was already here.
  "accept",
]);

export function useReviewKeys(actions: ReviewKeyActions, enabled = true): void {
  useEffect(() => {
    if (!enabled) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (isTypingTarget(event.target)) return;
      // Inside the page view the arrows and space scroll it, natively.
      if (isPanRegion(event.target) && SCROLL_KEYS.has(event.key)) return;
      const action = actionFor(event);
      if (!action) return;
      if (PREVENT_DEFAULT.has(action)) event.preventDefault();
      actions[action]();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [actions, enabled]);
}
