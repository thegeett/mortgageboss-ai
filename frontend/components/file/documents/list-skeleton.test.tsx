// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { DOCUMENT_COLUMNS, ListSkeleton } from "./document-list";

afterEach(cleanup);

/**
 * The loading state and the real table must not drift (LP-UI-034).
 *
 * They already had: the skeleton was a stack of `h-[58px]` bars while the rows
 * had become 53px, so every documents tab jumped on arrival. A hardcoded height
 * is a copy of a number that lives somewhere else, and nothing renders both and
 * compares — which is what these do.
 */
describe("ListSkeleton", () => {
  it("renders one cell per real column", () => {
    // A new column reaching the rows and not the skeleton makes the two disagree
    // about how many cells a row has, which reads as a column jumping sideways.
    render(<ListSkeleton />);
    const bodyRows = screen
      .getAllByRole("row")
      .filter((row) => row.querySelectorAll("td").length > 0);
    expect(bodyRows.length).toBeGreaterThan(0);
    // +1 for the details control's column — nameless, like the pipeline's
    // actions column, and present on the real row too.
    for (const row of bodyRows) {
      expect(row.querySelectorAll("td")).toHaveLength(DOCUMENT_COLUMNS.length + 1);
    }
  });

  it("carries the same column headers as the table", () => {
    render(<ListSkeleton />);
    for (const column of DOCUMENT_COLUMNS) {
      expect(screen.getByText(column.label)).toBeTruthy();
    }
  });

  it("gives the first cell TWO lines, because a real row has two", () => {
    // The standard name and the gist. Two lines are what make the row 53px
    // rather than 28px, so a one-line skeleton is a 25px jump.
    render(<ListSkeleton />);
    const firstBodyRow = screen
      .getAllByRole("row")
      .find((row) => row.querySelectorAll("td").length > 0);
    expect(firstBodyRow?.querySelector("td")?.querySelectorAll(".animate-pulse")).toHaveLength(2);
  });

  it("announces itself as busy, and the shapes stay out of the a11y tree", () => {
    const { container } = render(<ListSkeleton />);
    expect(container.querySelector("[aria-busy]")).toBeTruthy();
    for (const bar of container.querySelectorAll(".animate-pulse")) {
      expect(bar.getAttribute("aria-hidden")).toBe("true");
    }
  });

  it("hardcodes no pixel height", () => {
    // The failure this replaces. A bar sized in px is a copy of the row's height
    // that nothing updates when the density changes.
    const { container } = render(<ListSkeleton />);
    for (const bar of container.querySelectorAll(".animate-pulse")) {
      expect(bar.className).not.toMatch(/h-\[\d+px\]/);
    }
  });
});

describe("the group heading", () => {
  /**
   * The loaded list ALWAYS renders a category label and a count pill above each
   * table. The skeleton rendered a bare table, so the rows arrived lower than
   * they started on every documents tab — a shift no per-row height fix could
   * remove, because it is above the rows.
   *
   * Asserted on the elements rather than on a measured height: jsdom computes no
   * layout, so what this can pin is that the same structure is present, and the
   * classes carry the size the way the cells already do.
   */
  it("stands in for the heading the loaded list always has", () => {
    const { container } = render(<ListSkeleton />);
    const heading = container.querySelector("h3");
    expect(heading).not.toBeNull();
    // The type class is what gives the line its height; a hardcoded pixel height
    // here would be the same copied-number bug the row heights already had.
    expect(heading?.className).toContain("text-label");
  });

  it("puts the heading ABOVE the table, where the real one sits", () => {
    const { container } = render(<ListSkeleton />);
    const heading = container.querySelector("h3");
    const table = container.querySelector("table");
    expect(heading).not.toBeNull();
    expect(table).not.toBeNull();
    // compareDocumentPosition: FOLLOWING means the table comes after the heading.
    expect(heading?.compareDocumentPosition(table as Node)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
  });
});
