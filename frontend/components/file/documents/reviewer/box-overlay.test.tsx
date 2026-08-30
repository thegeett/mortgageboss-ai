// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

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
