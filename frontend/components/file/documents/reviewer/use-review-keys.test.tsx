// @vitest-environment jsdom
import { cleanup, fireEvent, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  type ReviewKeyActions,
  actionFor,
  isPanRegion,
  isTypingTarget,
  shortcutsEnabled,
  useReviewKeys,
} from "./use-review-keys";

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
    ["+", {}, "zoomIn"],
    ["=", {}, "zoomIn"],
    ["-", {}, "zoomOut"],
    ["_", {}, "zoomOut"],
    ["0", {}, "zoomReset"],
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
    zoomIn: vi.fn(),
    zoomOut: vi.fn(),
    zoomReset: vi.fn(),
    previousDocument: vi.fn(),
    nextDocument: vi.fn(),
    markReviewed: vi.fn(),
    toggleHelp: vi.fn(),
  };
}

function Harness({ on, enabled = true }: { on: ReviewKeyActions; enabled?: boolean }) {
  useReviewKeys(on, enabled);
  return (
    <>
      <input aria-label="a note" />
      <div data-pan-region>
        <button type="button" aria-label="inside the page">
          box
        </button>
      </div>
    </>
  );
}

describe("isPanRegion", () => {
  it("recognises anything inside the page view", () => {
    const region = document.createElement("div");
    region.setAttribute("data-pan-region", "");
    const child = document.createElement("button");
    region.appendChild(child);
    document.body.appendChild(region);
    expect(isPanRegion(child)).toBe(true);
    expect(isPanRegion(document.body)).toBe(false);
    expect(isPanRegion(null)).toBe(false);
    region.remove();
  });
});

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

  it("leaves the arrow keys to the page view when focus is inside it", () => {
    // A zoomed page has to be readable without a mouse. Stealing the arrows for
    // field navigation left it pannable only by dragging.
    const on = actions();
    const { getByLabelText } = render(<Harness on={on} />);
    const inside = getByLabelText("inside the page");
    for (const key of ["ArrowDown", "ArrowUp", "ArrowLeft", "ArrowRight", " "]) {
      fireEvent.keyDown(inside, { key });
    }
    expect(on.nextField).not.toHaveBeenCalled();
    expect(on.previousField).not.toHaveBeenCalled();
    expect(on.toggleOverlay).not.toHaveBeenCalled();
  });

  it("still answers its other keys inside the page view", () => {
    // Only the scroll keys are given up. Enter, R and the brackets are not how
    // anyone scrolls, and a reader with focus on the page still wants them.
    const on = actions();
    const { getByLabelText } = render(<Harness on={on} />);
    const inside = getByLabelText("inside the page");
    fireEvent.keyDown(inside, { key: "r" });
    fireEvent.keyDown(inside, { key: "]" });
    expect(on.reject).toHaveBeenCalledTimes(1);
    expect(on.nextDocument).toHaveBeenCalledTimes(1);
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

describe("shortcutsEnabled", () => {
  /**
   * The gap `isTypingTarget` cannot close.
   *
   * It guards the INPUT a correction is typed into. The verdict editor also has
   * buttons, and a `<button>` is not a typing target — so with the editor open and
   * focus on Cancel, `Enter` activated the button AND fired `accept`, recording an
   * acceptance on the field someone had opened in order to reject it.
   */
  it("stands down while the verdict editor is open", () => {
    expect(shortcutsEnabled({ helpOpen: false, editing: "gross_pay" })).toBe(false);
  });

  it("stands down while the shortcut sheet is open", () => {
    expect(shortcutsEnabled({ helpOpen: true, editing: null })).toBe(false);
  });

  it("is live when nothing owns the keyboard", () => {
    expect(shortcutsEnabled({ helpOpen: false, editing: null })).toBe(true);
  });
});

describe("the button-focus path the editor exposed", () => {
  it("does not treat a button as a place someone is typing", () => {
    // NOT a bug in isTypingTarget — a button genuinely is not a text field, and
    // shortcuts SHOULD work with one focused elsewhere on the page. It is the
    // reason the editor needs shortcutsEnabled: the guard was never going to
    // cover it, so something else had to.
    const button = document.createElement("button");
    expect(isTypingTarget(button)).toBe(false);
  });
});
