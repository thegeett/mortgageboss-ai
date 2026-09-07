// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { useRef } from "react";
import { usePan } from "./use-pan";

afterEach(cleanup);

/** A scroller whose overflow the test controls, since jsdom lays nothing out. */
function Harness({ overflow }: { overflow: boolean }) {
  const ref = useRef<HTMLDivElement | null>(null);
  const pan = usePan(ref);
  return (
    <div
      ref={(node) => {
        ref.current = node;
        if (!node) return;
        // jsdom reports 0 for every layout value; define the four the hook reads.
        const define = (name: string, value: number) =>
          Object.defineProperty(node, name, { value, configurable: true });
        define("scrollWidth", overflow ? 1000 : 400);
        define("clientWidth", 400);
        define("scrollHeight", overflow ? 800 : 300);
        define("clientHeight", 300);
      }}
      data-testid="scroller"
      data-pannable={pan.pannable}
      data-panning={pan.panning}
      onPointerDown={pan.onPointerDown}
    >
      <button type="button" data-testid="box">
        a highlight box
      </button>
    </div>
  );
}

const at = (x: number, y: number) => ({ clientX: x, clientY: y, button: 0 });

describe("usePan", () => {
  it("offers no grab when the page already fits", () => {
    // A grab cursor over a page that cannot move is a promise the screen does
    // not keep.
    render(<Harness overflow={false} />);
    expect(screen.getByTestId("scroller").dataset.pannable).toBe("false");
  });

  it("is pannable once the page overflows", () => {
    render(<Harness overflow />);
    expect(screen.getByTestId("scroller").dataset.pannable).toBe("true");
  });

  it("moves the content with the hand", () => {
    render(<Harness overflow />);
    const scroller = screen.getByTestId("scroller");
    scroller.scrollLeft = 0;
    scroller.scrollTop = 0;

    fireEvent.pointerDown(scroller, at(100, 100));
    fireEvent.pointerMove(window, at(60, 70));
    // Dragging LEFT reveals what is to the right, as every document viewer does.
    expect(scroller.scrollLeft).toBe(40);
    expect(scroller.scrollTop).toBe(30);
    fireEvent.pointerUp(window);
  });

  it("keeps panning when the pointer leaves the pane, and ends on release", () => {
    render(<Harness overflow />);
    const scroller = screen.getByTestId("scroller");
    fireEvent.pointerDown(scroller, at(100, 100));
    expect(scroller.dataset.panning).toBe("true");
    fireEvent.pointerMove(window, at(-500, -500));
    expect(scroller.scrollLeft).toBe(600);
    fireEvent.pointerUp(window);
    expect(scroller.dataset.panning).toBe("false");

    // And it stops listening: a later move must not drag the page.
    const settled = scroller.scrollLeft;
    fireEvent.pointerMove(window, at(0, 0));
    expect(scroller.scrollLeft).toBe(settled);
  });

  it("does not pan a page that fits", () => {
    render(<Harness overflow={false} />);
    const scroller = screen.getByTestId("scroller");
    scroller.scrollLeft = 0;
    fireEvent.pointerDown(scroller, at(100, 100));
    fireEvent.pointerMove(window, at(20, 20));
    expect(scroller.scrollLeft).toBe(0);
  });

  it("ignores anything but the left button", () => {
    // Right is a context menu; middle is the browser's own autoscroll.
    render(<Harness overflow />);
    const scroller = screen.getByTestId("scroller");
    scroller.scrollLeft = 0;
    fireEvent.pointerDown(scroller, { clientX: 100, clientY: 100, button: 2 });
    fireEvent.pointerMove(window, at(20, 20));
    expect(scroller.scrollLeft).toBe(0);
  });

  describe("the click that ends a drag", () => {
    it("is swallowed, so dragging off a highlight box does not select it", () => {
      // The boxes are buttons (LP-UI-031). Without this the processor moves the
      // page and the app navigates to whatever they started the drag on.
      render(<Harness overflow />);
      const scroller = screen.getByTestId("scroller");
      let clicked = false;
      screen.getByTestId("box").addEventListener("click", () => {
        clicked = true;
      });

      fireEvent.pointerDown(scroller, at(100, 100));
      fireEvent.pointerMove(window, at(40, 40));
      fireEvent.pointerUp(window);
      fireEvent.click(screen.getByTestId("box"));
      expect(clicked).toBe(false);
    });

    it("still lets a real click through", () => {
      // Holding still and clicking is not a drag, and selecting a field by
      // clicking its box is the whole of LP-UI-031's second direction.
      render(<Harness overflow />);
      const scroller = screen.getByTestId("scroller");
      let clicked = false;
      screen.getByTestId("box").addEventListener("click", () => {
        clicked = true;
      });

      fireEvent.pointerDown(scroller, at(100, 100));
      fireEvent.pointerMove(window, at(101, 101)); // within the threshold
      fireEvent.pointerUp(window);
      fireEvent.click(screen.getByTestId("box"));
      expect(clicked).toBe(true);
    });
  });
});
