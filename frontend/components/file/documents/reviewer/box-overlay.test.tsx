// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { FieldBox } from "@/lib/api/field-boxes";
import { BoxOverlay } from "./box-overlay";

afterEach(cleanup);

const BOXES: FieldBox[] = [
  { field_key: "gross_pay", page: 1, x0: 0.1, y0: 0.2, x1: 0.5, y1: 0.25 },
  { field_key: "employer", page: 1, x0: 0.1, y0: 0.4, x1: 0.6, y1: 0.45 },
  { field_key: "pay_date", page: 2, x0: 0.1, y0: 0.1, x1: 0.3, y1: 0.15 },
];

function renderOverlay(props: Partial<Parameters<typeof BoxOverlay>[0]> = {}) {
  const onSelect = vi.fn();
  const onHover = vi.fn();
  render(
    <BoxOverlay
      boxes={BOXES}
      page={1}
      selected={null}
      hovered={null}
      showAll={false}
      onSelect={onSelect}
      onHover={onHover}
      labelFor={(key) => (key === "gross_pay" ? "Gross pay" : key)}
      {...props}
    />,
  );
  return { onSelect, onHover };
}

describe("BoxOverlay", () => {
  it("draws only the boxes belonging to the page on screen", () => {
    renderOverlay();
    expect(screen.getAllByRole("button")).toHaveLength(2);
    renderOverlay({ page: 2 });
    // The page-2 render adds exactly one more.
    expect(screen.getAllByRole("button")).toHaveLength(3);
  });

  it("renders nothing at all when the page has no boxes", () => {
    const { container } = render(
      <BoxOverlay
        boxes={BOXES}
        page={7}
        selected={null}
        hovered={null}
        showAll={false}
        onSelect={vi.fn()}
        onHover={vi.fn()}
        labelFor={(key) => key}
      />,
    );
    expect(container.innerHTML).toBe("");
  });

  it("positions a box as a percentage of the page, not in pixels", () => {
    renderOverlay();
    const box = screen.getByRole("button", { name: "Highlight for Gross pay" });
    expect(box.style.left).toBe("10%");
    expect(box.style.top).toBe("20%");
    expect(box.style.width).toBe("40%");
    // Rounded: the raw subtraction is 4.999999999999999.
    expect(box.style.height).toBe("5%");
  });

  it("names a box by its field, never by the borrower text underneath", () => {
    renderOverlay();
    expect(screen.getByRole("button", { name: "Highlight for Gross pay" })).toBeTruthy();
  });

  it("hides the boxes that are neither selected nor hovered", () => {
    renderOverlay({ selected: "gross_pay" });
    const selected = screen.getByRole("button", { name: "Highlight for Gross pay" });
    const other = screen.getByRole("button", { name: "Highlight for employer" });
    expect(selected.className).toContain("opacity-100");
    expect(other.className).toContain("opacity-0");
    expect(selected.getAttribute("aria-pressed")).toBe("true");
  });

  it("actually draws its ring — the class survives tailwind-merge", () => {
    // `outline` and `outline-1` are one group to tailwind-merge, so writing both
    // leaves `outline-style: none` and a box that is present, positioned, and
    // invisible. Asserting on the class list catches that; asserting on opacity
    // did not.
    renderOverlay({ selected: "gross_pay" });
    const box = screen.getByRole("button", { name: "Highlight for Gross pay" });
    expect(box.className).toContain("[outline-style:solid]");
    expect(box.className).toContain("outline-2");
  });

  it("reveals every candidate while Alt is held", () => {
    renderOverlay({ showAll: true });
    for (const box of screen.getAllByRole("button")) {
      expect(box.className).toContain("opacity-100");
    }
  });

  it("reports a click as a field, so the caller can navigate rather than write", () => {
    const { onSelect } = renderOverlay({ selected: "gross_pay" });
    fireEvent.click(screen.getByRole("button", { name: "Highlight for employer" }));
    expect(onSelect).toHaveBeenCalledWith("employer");
  });

  it("links hover and keyboard focus to the same field", () => {
    const { onHover } = renderOverlay();
    const box = screen.getByRole("button", { name: "Highlight for employer" });
    fireEvent.mouseEnter(box);
    expect(onHover).toHaveBeenCalledWith("employer");
    fireEvent.mouseLeave(box);
    expect(onHover).toHaveBeenLastCalledWith(null);
    // A processor reviewing with the keyboard reaches a box by focus, and the
    // link back to the field has to work the same way there.
    fireEvent.focus(box);
    expect(onHover).toHaveBeenLastCalledWith("employer");
  });
});

describe("the selected box is brought into view (LP-703 review follow-up)", () => {
  /**
   * Selecting a field already jumped to the box's PAGE, and that was the whole of
   * it. On a zoomed page — where the pan region scrolls — selecting a field
   * highlighted a rectangle somewhere outside the visible area and the screen
   * appeared not to respond. The fields pane has had the mirror of this since
   * LP-UI-030; the document side never did. Reported from the app.
   */
  // RECORDS WHICH ELEMENT SCROLLED, not merely that something did. The mock sits
  // on `Element.prototype`, so it is the SAME function object on every element —
  // asserting `element.scrollIntoView` was called proves nothing about which
  // element. A first version did exactly that and survived a mutation putting the
  // ref on every box.
  const scrolls: { el: Element; arg: unknown }[] = [];

  beforeEach(() => {
    scrolls.length = 0;
    Element.prototype.scrollIntoView = vi.fn(function (this: Element, arg) {
      scrolls.push({ el: this, arg });
    }) as unknown as typeof Element.prototype.scrollIntoView;
  });

  const SCROLL_BOXES: FieldBox[] = [
    { field_key: "gross_pay", page: 1, x0: 0.1, y0: 0.1, x1: 0.3, y1: 0.15 },
    { field_key: "net_pay", page: 1, x0: 0.1, y0: 0.8, x1: 0.3, y1: 0.85 },
  ];

  function overlay(selected: string | null) {
    return (
      <BoxOverlay
        boxes={SCROLL_BOXES}
        page={1}
        selected={selected}
        hovered={null}
        showAll={false}
        onSelect={vi.fn()}
        onHover={vi.fn()}
        labelFor={(k) => k}
      />
    );
  }

  it("scrolls to the box when a field is selected", () => {
    const { rerender } = render(overlay(null));
    expect(scrolls).toHaveLength(0);
    rerender(overlay("net_pay"));
    expect(scrolls).toHaveLength(1);
  });

  it("uses `nearest`, so a box already on screen does not move", () => {
    // A processor who clicked a box must not have the page jump out from under
    // the click.
    render(overlay("net_pay"));
    expect(scrolls[0]?.arg).toMatchObject({ block: "nearest", inline: "nearest" });
  });

  it("does NOT scroll on hover", () => {
    // Hover is how a processor skims. Scrolling the page under a moving pointer
    // would make the document unusable.
    //
    // SOMETHING IS SELECTED THROUGHOUT, which is what makes this a test of the
    // guard rather than of the ref. With nothing selected the ref is never
    // attached and no scroll can happen for any reason — so a first version of
    // this passed with the hover guard removed entirely.
    const { rerender } = render(
      <BoxOverlay
        boxes={SCROLL_BOXES}
        page={1}
        selected="gross_pay"
        hovered={null}
        showAll={false}
        onSelect={vi.fn()}
        onHover={vi.fn()}
        labelFor={(k) => k}
      />,
    );
    expect(scrolls).toHaveLength(1); // the selection itself

    rerender(
      <BoxOverlay
        boxes={SCROLL_BOXES}
        page={1}
        selected="gross_pay"
        hovered="net_pay"
        showAll={false}
        onSelect={vi.fn()}
        onHover={vi.fn()}
        labelFor={(k) => k}
      />,
    );
    expect(scrolls, "moving the pointer must not scroll the page").toHaveLength(1);
  });

  it("scrolls to the SELECTED box, not merely to some box", () => {
    // The control, and it has to compare ELEMENTS. `scrollIntoView` is one shared
    // function on `Element.prototype`, so "was it called on this element" is
    // unanswerable through the spy — only the recorded `this` distinguishes a ref
    // on the selected box from a ref on every box.
    const { rerender } = render(overlay(null));
    rerender(overlay("gross_pay"));
    const target = document.querySelector('[aria-label="Highlight for gross_pay"]');
    expect(target).toBeTruthy();
    expect(scrolls).toHaveLength(1);
    expect(scrolls[0]?.el).toBe(target);
  });
});
