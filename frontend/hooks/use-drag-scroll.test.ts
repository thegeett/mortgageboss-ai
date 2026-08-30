// @vitest-environment jsdom
/**
 * The hard half of drag-to-scroll is not the cursor — it is that these strips are made of LINKS AND
 * BUTTONS, so a drag that ends on a tab would navigate. These pin the three decisions that follow
 * from that, and the one that keeps the cursor honest.
 */
import { act, renderHook } from "@testing-library/react";
import { useRef } from "react";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { useDragScroll } from "./use-drag-scroll";

beforeAll(() => {
  // jsdom has no layout, so nothing overflows and no ResizeObserver exists.
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
});

/** A strip that overflows by default, with the pointer-capture API jsdom omits. */
function mountStrip({ scrollWidth = 800, clientWidth = 400 } = {}) {
  const el = document.createElement("div");
  Object.defineProperty(el, "scrollWidth", { value: scrollWidth, configurable: true });
  Object.defineProperty(el, "clientWidth", { value: clientWidth, configurable: true });
  el.scrollLeft = 0;
  el.setPointerCapture = vi.fn();
  el.releasePointerCapture = vi.fn();
  el.hasPointerCapture = vi.fn(() => false);
  document.body.append(el);
  return el;
}

function pointer(type: string, clientX: number) {
  const event = new MouseEvent(type, { clientX, bubbles: true, button: 0 });
  Object.defineProperty(event, "pointerId", { value: 1 });
  Object.defineProperty(event, "pointerType", { value: "mouse" });
  return event as unknown as PointerEvent;
}

function useAttached(el: HTMLElement) {
  const drag = useDragScroll<HTMLElement>();
  const done = useRef(false);
  if (!done.current) {
    drag.ref.current = el;
    done.current = true;
  }
  return drag;
}

describe("useDragScroll", () => {
  it("scrolls the strip while the pointer drags", () => {
    const el = mountStrip();
    renderHook(() => useAttached(el));

    act(() => {
      el.dispatchEvent(pointer("pointerdown", 300));
      el.dispatchEvent(pointer("pointermove", 250));
    });
    expect(el.scrollLeft).toBe(50); // dragged left by 50 -> scrolled right by 50
  });

  it("swallows the click that ends a real drag", () => {
    const el = mountStrip();
    renderHook(() => useAttached(el));
    const onClick = vi.fn();
    el.addEventListener("click", onClick);

    act(() => {
      el.dispatchEvent(pointer("pointerdown", 300));
      el.dispatchEvent(pointer("pointermove", 200));
      el.dispatchEvent(pointer("pointerup", 200));
      el.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(onClick).not.toHaveBeenCalled(); // otherwise dragging the strip navigates
  });

  it("lets a plain click through", () => {
    const el = mountStrip();
    renderHook(() => useAttached(el));
    const onClick = vi.fn();
    el.addEventListener("click", onClick);

    act(() => {
      el.dispatchEvent(pointer("pointerdown", 300));
      el.dispatchEvent(pointer("pointermove", 302)); // inside the threshold — a hand tremor, not a drag
      el.dispatchEvent(pointer("pointerup", 302));
      el.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("offers no grab cursor when there is nothing to scroll", () => {
    const el = mountStrip({ scrollWidth: 400, clientWidth: 400 });
    const { result } = renderHook(() => useAttached(el));
    // A grab cursor on a strip that fits promises something that does nothing.
    expect(result.current.className).toBe("");
  });
});

describe("useDragScroll on a table", () => {
  it("leaves a table that fits entirely alone", () => {
    // The reason tables were safe to add: text selection inside them is untouched unless the table is
    // genuinely wider than its container, and most are not.
    const el = mountStrip({ scrollWidth: 600, clientWidth: 600 });
    renderHook(() => useAttached(el));
    const onClick = vi.fn();
    el.addEventListener("click", onClick);

    act(() => {
      el.dispatchEvent(pointer("pointerdown", 400));
      el.dispatchEvent(pointer("pointermove", 200)); // a long drag — a text selection, not a pan
      el.dispatchEvent(pointer("pointerup", 200));
      el.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(el.scrollLeft).toBe(0); // nothing panned
    expect(onClick).toHaveBeenCalledTimes(1); // and the click was not swallowed
  });
});
