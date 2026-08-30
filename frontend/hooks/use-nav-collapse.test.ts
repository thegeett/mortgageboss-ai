// @vitest-environment jsdom
import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { NAV_COOKIE, useNavCollapse } from "./use-nav-collapse";

function cookieValue(): string | null {
  const found = document.cookie.split("; ").find((c) => c.startsWith(`${NAV_COOKIE}=`));
  return found ? (found.split("=")[1] ?? "") : null;
}

afterEach(() => {
  // Vitest runs without `globals`, so RTL never registers its auto-cleanup and a
  // hook from an earlier test stays mounted — each one holding its own window
  // keydown listener, so N mounts toggle N times per keypress.
  cleanup();
  document.documentElement.removeAttribute("data-nav");
  document.cookie = `${NAV_COOKIE}=;path=/;max-age=0`;
});

describe("useNavCollapse", () => {
  it("takes the DOM attribute as the source of truth, not its own state", () => {
    // The attribute is what the CSS reads, so it is what the user SEES. `toggle`
    // used to compute the next state from the React value instead, which meant
    // any divergence cost a silent no-op press. Mounting expanded and then
    // collapsing the document from outside React is that divergence: state says
    // expanded, the pixels say collapsed. Toggling must agree with the pixels.
    const { result } = renderHook(() => useNavCollapse());
    expect(result.current.collapsed).toBe(false);

    document.documentElement.dataset.nav = "collapsed";
    act(() => result.current.toggle());

    // From collapsed, one toggle expands. Computing from the stale React value
    // would have collapsed it again — a press that visibly does nothing.
    expect(document.documentElement.dataset.nav).toBeUndefined();
    expect(result.current.collapsed).toBe(false);
  });

  it("adopts what the server stamped without changing it", () => {
    document.documentElement.dataset.nav = "collapsed";
    const { result } = renderHook(() => useNavCollapse());
    expect(result.current.collapsed).toBe(true);
    expect(document.documentElement.dataset.nav).toBe("collapsed");
  });

  it("persists collapsed, and DELETES the cookie when expanding", () => {
    // The server tests for "collapsed" exactly, so `expanded` and no-cookie mean
    // the same thing. Writing both is two spellings of one state.
    const { result } = renderHook(() => useNavCollapse());
    act(() => result.current.toggle());
    expect(cookieValue()).toBe("collapsed");
    act(() => result.current.toggle());
    expect(cookieValue()).toBeNull();
  });

  it("toggles on Cmd+B and Ctrl+B", () => {
    const { result } = renderHook(() => useNavCollapse());
    act(() => {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "b", metaKey: true }));
    });
    expect(result.current.collapsed).toBe(true);
    act(() => {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "b", ctrlKey: true }));
    });
    expect(result.current.collapsed).toBe(false);
  });

  it("leaves Cmd+B alone in rich text, where it means bold", () => {
    const editor = document.createElement("div");
    editor.contentEditable = "true";
    // jsdom does not implement isContentEditable off the attribute.
    Object.defineProperty(editor, "isContentEditable", { value: true });
    document.body.appendChild(editor);
    const { result } = renderHook(() => useNavCollapse());

    act(() => {
      editor.dispatchEvent(
        new KeyboardEvent("keydown", { key: "b", metaKey: true, bubbles: true }),
      );
    });
    expect(result.current.collapsed).toBe(false);
    editor.remove();
  });

  it("still toggles from a plain input, where Cmd+B means nothing native", () => {
    const input = document.createElement("input");
    document.body.appendChild(input);
    const { result } = renderHook(() => useNavCollapse());

    act(() => {
      input.dispatchEvent(new KeyboardEvent("keydown", { key: "b", metaKey: true, bubbles: true }));
    });
    expect(result.current.collapsed).toBe(true);
    input.remove();
  });

  it("ignores Cmd+Shift+B and Cmd+Alt+B, which belong to the browser", () => {
    const { result } = renderHook(() => useNavCollapse());
    act(() => {
      window.dispatchEvent(
        new KeyboardEvent("keydown", { key: "b", metaKey: true, shiftKey: true }),
      );
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "b", metaKey: true, altKey: true }));
    });
    expect(result.current.collapsed).toBe(false);
  });
});
