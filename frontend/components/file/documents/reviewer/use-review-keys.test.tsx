// @vitest-environment jsdom
import { cleanup, fireEvent, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { type ReviewKeyActions, actionFor, isTypingTarget, useReviewKeys } from "./use-review-keys";

afterEach(cleanup);

const NONE = {
  key: "",
  shiftKey: false,
  metaKey: false,
  ctrlKey: false,
  altKey: false,
};

describe("actionFor — the binding table", () => {
  it.each([
    ["Enter", {}, "accept"],
    ["Enter", { shiftKey: true }, "acceptAndAdvance"],
    ["Enter", { metaKey: true }, "markReviewed"],
    ["Enter", { ctrlKey: true }, "markReviewed"],
    ["Tab", {}, "nextField"],
    ["Tab", { shiftKey: true }, "previousField"],
    ["ArrowDown", {}, "nextField"],
    ["ArrowUp", {}, "previousField"],
    ["e", {}, "edit"],
    ["E", {}, "edit"],
    ["r", {}, "reject"],
    ["R", {}, "reject"],
    [" ", {}, "toggleOverlay"],
    ["[", {}, "previousDocument"],
    ["]", {}, "nextDocument"],
    ["?", {}, "toggleHelp"],
  ])("binds %s %o to %s", (key, mods, expected) => {
    expect(actionFor({ ...NONE, key, ...mods })).toBe(expected);
  });

  it("reads ⌘Enter as mark-reviewed, not as accept", () => {
    // Enter with a modifier is still Enter; testing the bare key first would
    // swallow it and mark-reviewed would be unreachable.
    expect(actionFor({ ...NONE, key: "Enter", metaKey: true })).toBe("markReviewed");
  });

  it("ignores a letter with Alt held — that is the box-reveal gesture", () => {
    expect(actionFor({ ...NONE, key: "e", altKey: true })).toBeNull();
  });

  it("ignores a letter with a command modifier — that is the browser's", () => {
    expect(actionFor({ ...NONE, key: "r", metaKey: true })).toBeNull();
    expect(actionFor({ ...NONE, key: "e", ctrlKey: true })).toBeNull();
  });

  it("ignores keys it does not bind", () => {
    for (const key of ["a", "z", "1", "Escape", "F5"]) {
      expect(actionFor({ ...NONE, key })).toBeNull();
    }
  });
});

describe("isTypingTarget", () => {
  it("recognises the fields a person types into", () => {
    for (const tag of ["input", "textarea", "select"]) {
      const el = document.createElement(tag);
      expect(isTypingTarget(el)).toBe(true);
    }
  });

  it("recognises a contenteditable, which is a div", () => {
    const el = document.createElement("div");
    el.contentEditable = "true";
    // jsdom does not derive isContentEditable from the attribute.
    Object.defineProperty(el, "isContentEditable", { value: true });
    expect(isTypingTarget(el)).toBe(true);
  });

  it("does not treat an ordinary element as typing", () => {
    expect(isTypingTarget(document.createElement("button"))).toBe(false);
    expect(isTypingTarget(null)).toBe(false);
  });
});

function actions(): ReviewKeyActions {
  return {
    nextField: vi.fn(),
    previousField: vi.fn(),
    accept: vi.fn(),
    acceptAndAdvance: vi.fn(),
    edit: vi.fn(),
    reject: vi.fn(),
    toggleOverlay: vi.fn(),
    previousDocument: vi.fn(),
    nextDocument: vi.fn(),
    markReviewed: vi.fn(),
    toggleHelp: vi.fn(),
  };
}

function Harness({ on, enabled = true }: { on: ReviewKeyActions; enabled?: boolean }) {
  useReviewKeys(on, enabled);
  return <input aria-label="a note" />;
}

describe("useReviewKeys", () => {
  it("runs the bound action", () => {
    const on = actions();
    render(<Harness on={on} />);
    fireEvent.keyDown(window, { key: "r" });
    expect(on.reject).toHaveBeenCalledTimes(1);
  });

  it("NEVER fires while a text input has focus", () => {
    // `R` is a rejection and `E` opens an editor. Typing "Rate" into a correction
    // box would reject four fields and open the editor twice.
    const on = actions();
    const { getByLabelText } = render(<Harness on={on} />);
    const input = getByLabelText("a note");
    for (const key of ["r", "e", "R", " ", "Enter", "]"]) {
      fireEvent.keyDown(input, { key });
    }
    for (const action of Object.values(on)) expect(action).not.toHaveBeenCalled();
  });

  it("stops listening when disabled", () => {
    const on = actions();
    render(<Harness on={on} enabled={false} />);
    fireEvent.keyDown(window, { key: "r" });
    expect(on.reject).not.toHaveBeenCalled();
  });

  it("unbinds on unmount, so a closed reviewer does not still answer keys", () => {
    const on = actions();
    const { unmount } = render(<Harness on={on} />);
    unmount();
    fireEvent.keyDown(window, { key: "r" });
    expect(on.reject).not.toHaveBeenCalled();
  });

  it("takes the default away from the keys the browser would also act on", () => {
    const on = actions();
    render(<Harness on={on} />);
    // Space scrolls, Tab moves focus out of the reviewer — each would happen ON
    // TOP of our action.
    for (const key of [" ", "Tab", "ArrowDown"]) {
      const prevented = !fireEvent.keyDown(window, { key, cancelable: true });
      expect(prevented, `${key} should be prevented`).toBe(true);
    }
  });

  it("leaves the default alone for keys the browser does not fight us over", () => {
    const on = actions();
    render(<Harness on={on} />);
    const prevented = !fireEvent.keyDown(window, { key: "r", cancelable: true });
    expect(prevented).toBe(false);
  });
});
