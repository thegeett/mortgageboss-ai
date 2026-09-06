// @vitest-environment jsdom
/**
 * Clicking a box must bring its field into view, not merely tint it.
 *
 * The fields pane scrolls (`ReviewerShell`'s section is `overflow-y-auto`) and
 * selection only changed a background colour — so on a document with more
 * fields than fit, clicking a box on the page highlighted a row below the fold
 * and the ticket's headline interaction appeared to do nothing in the direction
 * it was built for.
 */
import { cleanup, fireEvent, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const detail = vi.hoisted(() => ({ data: undefined as unknown }));
vi.mock("@/lib/api/documents", () => ({
  useDocumentDetail: () => ({ ...detail, isPending: false, isError: false }),
}));

import { extractionFields } from "@/lib/loan-files/documents";
import { ReviewerFields } from "./reviewer-fields";

/** The rows the PAGE derives and passes down (LP-703 review). */
const FIELDS = extractionFields(
  Object.fromEntries(
    ["employer_name", "gross_pay", "pay_date", "net_pay"].map((k) => [
      k,
      { value: `v-${k}`, source: { page: 1, snippet: k } },
    ]),
  ),
);

const scrolls: { block?: string }[] = [];

beforeEach(() => {
  scrolls.length = 0;
  Element.prototype.scrollIntoView = vi.fn(function (this: Element, arg) {
    scrolls.push((arg as { block?: string }) ?? {});
  }) as unknown as typeof Element.prototype.scrollIntoView;
  detail.data = {
    status: "completed",
    current_extraction: {
      extracted_data: Object.fromEntries(
        ["employer_name", "gross_pay", "pay_date", "net_pay"].map((k) => [
          k,
          { value: `v-${k}`, source: { page: 1, snippet: k } },
        ]),
      ),
    },
  };
});
afterEach(cleanup);

describe("the selected field is brought into view", () => {
  it("scrolls to the row when the selection changes", () => {
    const { rerender } = render(<ReviewerFields documentId="d1" fields={FIELDS} selected={null} />);
    expect(scrolls).toHaveLength(0);

    rerender(<ReviewerFields documentId="d1" fields={FIELDS} selected="net_pay" />);
    expect(scrolls).toHaveLength(1);
  });

  it("uses `nearest`, so a row already on screen does not move", () => {
    // Clicking a row directly must not scroll the list out from under the
    // pointer — `nearest` is a no-op for anything already visible.
    const { rerender } = render(<ReviewerFields documentId="d1" fields={FIELDS} selected={null} />);
    rerender(<ReviewerFields documentId="d1" fields={FIELDS} selected="gross_pay" />);
    expect(scrolls[0]?.block).toBe("nearest");
  });

  it("does not scroll when nothing is selected", () => {
    render(<ReviewerFields documentId="d1" fields={FIELDS} selected={null} />);
    expect(scrolls).toHaveLength(0);
  });

  it("follows the selection as it moves between fields", () => {
    const { rerender } = render(
      <ReviewerFields documentId="d1" fields={FIELDS} selected="employer_name" />,
    );
    rerender(<ReviewerFields documentId="d1" fields={FIELDS} selected="pay_date" />);
    rerender(<ReviewerFields documentId="d1" fields={FIELDS} selected="net_pay" />);
    expect(scrolls.length).toBeGreaterThanOrEqual(3);
  });
});

describe("the WHOLE ROW selects the field, not just its name", () => {
  /**
   * The comment above the row has claimed "the whole row is the control rather
   * than a small affordance inside it" since LP-UI-030, while the click handler
   * sat on the label button alone. So clicking a value, a source snippet or the
   * space beside them did nothing, and a processor reading a row had to go back
   * and hit the one word at its left edge to see the box. Reported from the app.
   */
  it("selects when the VALUE is clicked", () => {
    const onSelect = vi.fn();
    const { getByText } = render(
      <ReviewerFields documentId="d1" fields={FIELDS} onSelect={onSelect} />,
    );
    fireEvent.click(getByText("v-gross_pay"));
    expect(onSelect).toHaveBeenCalledWith("gross_pay");
  });

  it("selects when the SOURCE SNIPPET is clicked", () => {
    // The quoted text under the value — the part a processor actually reads when
    // there is no box to look at, and the largest click target on the row.
    const onSelect = vi.fn();
    const { container } = render(
      <ReviewerFields documentId="d1" fields={FIELDS} onSelect={onSelect} />,
    );
    const snippet = [...container.querySelectorAll("span")].find((el) =>
      el.textContent?.includes("\u201Cgross_pay\u201D"),
    );
    expect(snippet, "the row should render its source snippet").toBeTruthy();
    fireEvent.click(snippet as Element);
    expect(onSelect).toHaveBeenCalledWith("gross_pay");
  });

  it("still selects when the LABEL is clicked — the keyboard path", () => {
    // The label stays a real button because an <li> serves no keyboard user, and
    // the row cannot become one without nesting the buttons it already contains.
    const onSelect = vi.fn();
    const { getByRole } = render(
      <ReviewerFields documentId="d1" fields={FIELDS} onSelect={onSelect} />,
    );
    fireEvent.click(getByRole("button", { name: "Gross pay" }));
    expect(onSelect).toHaveBeenCalledWith("gross_pay");
  });
});
