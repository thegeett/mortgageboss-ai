// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SHORTCUTS, ShortcutSheet } from "./shortcut-sheet";
import { REVIEW_KEY_ACTIONS, type ReviewKeyActions, actionFor } from "./use-review-keys";

afterEach(cleanup);

const NONE = { key: "", shiftKey: false, metaKey: false, ctrlKey: false, altKey: false };

describe("ShortcutSheet", () => {
  it("lists every shortcut when open", () => {
    render(<ShortcutSheet open onClose={vi.fn()} />);
    for (const shortcut of SHORTCUTS) {
      expect(screen.getByText(shortcut.keys)).toBeTruthy();
    }
  });

  it("shows nothing when closed", () => {
    render(<ShortcutSheet open={false} onClose={vi.fn()} />);
    expect(screen.queryByText("Keyboard shortcuts")).toBeNull();
  });

  it("says that shortcuts pause while typing, because that is surprising", () => {
    render(<ShortcutSheet open onClose={vi.fn()} />);
    expect(screen.getByText(/pause while you are typing/)).toBeTruthy();
  });
});

describe("the sheet and the bindings agree", () => {
  /**
   * The sheet is written by hand rather than generated, so this is what stops it
   * drifting into a lie. Generating it would couple them in the direction that
   * HIDES a bug: a binding that silently changed would change the sheet with it
   * and still look right.
   */
  const DOCUMENTED: Array<[string, Parameters<typeof actionFor>[0], keyof ReviewKeyActions]> = [
    ["↓ / ↑", { ...NONE, key: "ArrowDown" }, "nextRow"],
    ["Tab", { ...NONE, key: "Tab" }, "nextField"],
    ["Shift+Tab", { ...NONE, key: "Tab", shiftKey: true }, "previousField"],
    ["Enter", { ...NONE, key: "Enter" }, "accept"],
    ["Shift+Enter", { ...NONE, key: "Enter", shiftKey: true }, "acceptAndAdvance"],
    ["E", { ...NONE, key: "e" }, "edit"],
    ["R", { ...NONE, key: "r" }, "reject"],
    ["Space", { ...NONE, key: " " }, "toggleOverlay"],
    ["+ / -", { ...NONE, key: "+" }, "zoomIn"],
    ["0", { ...NONE, key: "0" }, "zoomReset"],
    ["[ / ]", { ...NONE, key: "[" }, "previousDocument"],
    ["⌘Enter", { ...NONE, key: "Enter", metaKey: true }, "markReviewed"],
    ["?", { ...NONE, key: "?" }, "toggleHelp"],
  ];

  it.each(DOCUMENTED)("%s really does what the sheet says", (label, event, action) => {
    expect(SHORTCUTS.some((s) => s.keys === label)).toBe(true);
    expect(actionFor(event)).toBe(action);
  });

  it("documents every binding the table has", () => {
    // A shortcut that works and is not in the sheet is a shortcut nobody finds.
    // `Alt (hold)` is documented here and lives in LP-UI-031, not in actionFor.
    const documented = new Set(DOCUMENTED.map(([label]) => label));
    const undocumented = SHORTCUTS.map((s) => s.keys).filter(
      (keys) => !documented.has(keys) && keys !== "Alt (hold)",
    );
    expect(undocumented).toEqual([]);
  });

  it("documents every ACTION the reviewer has, not just every row of the sheet", () => {
    // The check above only proves the sheet's rows are real. It would pass with a
    // new action bound to a key nobody had written down — which is how ↓ ran
    // `nextField` while the sheet claimed it was the same key as Tab (LP-701).
    // The counterparts are reached by a modifier of a documented key.
    const COUNTERPART: ReadonlySet<keyof ReviewKeyActions> = new Set([
      "previousRow",
      "zoomOut",
      "nextDocument",
    ]);
    const acted = new Set(DOCUMENTED.map(([, , action]) => action));
    // ENUMERATED FROM THE SOURCE, not restated. A local copy typed
    // `keyof ReviewKeyActions` catches a REMOVED action and misses an ADDED one —
    // the new name is simply absent, and a list that never mentions it cannot
    // notice it. `REVIEW_KEY_ACTIONS` is guarded against the interface in both
    // directions where it is declared.
    const every = REVIEW_KEY_ACTIONS;
    expect(every.filter((a) => !acted.has(a) && !COUNTERPART.has(a))).toEqual([]);
  });
});
