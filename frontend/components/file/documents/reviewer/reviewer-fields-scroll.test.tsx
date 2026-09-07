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
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const detail = vi.hoisted(() => ({
  data: undefined as unknown,
  isPending: false,
  isError: false,
}));
vi.mock("@/lib/api/documents", () => ({
  useDocumentDetail: () => detail,
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
  detail.isPending = false;
  detail.isError = false;
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

  it("scrolls once the ROWS arrive, not only when the selection changes", () => {
    // SELECTION COMES FROM THE DOCUMENT TOO, and the two sides load on separate
    // queries. A processor who clicks a box while this pane is still a skeleton
    // set `selected` in a commit with no rows in it and a null ref; the rows
    // arrived later with the selection unchanged, so nothing ran again and the
    // row stayed below the fold — the exact symptom this effect exists to remove.
    //
    // This side is where the box overlay copied the pattern FROM, so the same gap
    // was on both.
    detail.isPending = true;
    const { rerender } = render(<ReviewerFields documentId="d1" fields={[]} selected="net_pay" />);
    expect(scrolls, "there is no row to scroll to yet").toHaveLength(0);

    detail.isPending = false;
    rerender(<ReviewerFields documentId="d1" fields={FIELDS} selected="net_pay" />);
    expect(scrolls).toHaveLength(1);
  });

  it("does not scroll for a selection this document has no row for", () => {
    // The control for the test above: "the rows arrived" must mean THIS row, not
    // any row. A key from the document the processor just navigated away from
    // must not scroll the new document's list to whatever happens to be first.
    render(
      <ReviewerFields documentId="d1" fields={FIELDS} selected="a_key_from_another_document" />,
    );
    expect(scrolls).toHaveLength(0);
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

  it("pointing at anywhere in the row hovers its field, and leaving clears it", () => {
    // LP-710 MOVED hover from the label button to the row, so that pointing at a
    // value emphasises its box the way pointing at the label always did — and
    // nothing tested it in either place. The handlers could be deleted with the
    // whole suite green, which is how a behaviour this pane is built around gets
    // to disappear silently.
    const onHover = vi.fn();
    render(<ReviewerFields documentId="d1" fields={FIELDS} selected={null} onHover={onHover} />);
    const row = screen.getByText("v-gross_pay").closest("li");
    expect(row).toBeTruthy();
    fireEvent.mouseEnter(row as Element);
    expect(onHover).toHaveBeenCalledWith("gross_pay");
    fireEvent.mouseLeave(row as Element);
    expect(onHover).toHaveBeenLastCalledWith(null);
  });

  it("selects ONCE when the label is activated, not once per handler", () => {
    // The row and the label each carried a handler calling the same thing, so a
    // label click fired `onSelect` twice — harmless only because selection happens
    // to be idempotent, and invisible to every existing test. Neither copy could be
    // held: delete either one and the other still selects, with the whole suite
    // green. There is one handler now, on the row, and this counts the calls.
    const onSelect = vi.fn();
    render(<ReviewerFields documentId="d1" fields={FIELDS} selected={null} onSelect={onSelect} />);
    fireEvent.click(screen.getByRole("button", { name: "Gross pay" }));
    expect(onSelect.mock.calls).toHaveLength(1);
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

describe("editing is reachable with a mouse (LP-711)", () => {
  /**
   * LP-703 built correcting a value, removing a field and adding one — all
   * undoable, all reaching the rule engine — and `setEditing` was called ONLY
   * from the `E` and `R` key handlers. A processor working with a mouse could
   * select a field, read it, and change nothing: the whole feature sat behind a
   * shortcut discoverable only by opening the `?` sheet.
   */
  it("offers Edit on the SELECTED row", () => {
    const { getByRole } = render(
      <ReviewerFields documentId="d1" fields={FIELDS} selected="gross_pay" onEdit={vi.fn()} />,
    );
    expect(getByRole("button", { name: "Edit" })).toBeTruthy();
  });

  it("offers it on NO other row", () => {
    // A control on forty rows at once is the chrome LP-UI-032 spent a ticket
    // removing. Without this the test above would pass for a button rendered
    // unconditionally.
    const { queryAllByRole } = render(
      <ReviewerFields documentId="d1" fields={FIELDS} selected="gross_pay" onEdit={vi.fn()} />,
    );
    expect(queryAllByRole("button", { name: "Edit" })).toHaveLength(1);
  });

  it("names the field it sits on, rather than trusting the selection to settle", () => {
    const onEdit = vi.fn();
    const { getByRole } = render(
      <ReviewerFields documentId="d1" fields={FIELDS} selected="gross_pay" onEdit={onEdit} />,
    );
    fireEvent.click(getByRole("button", { name: "Edit" }));
    expect(onEdit).toHaveBeenCalledWith("gross_pay");
  });

  it("is not offered while that row's editor is already open", () => {
    const { queryByRole } = render(
      <ReviewerFields
        documentId="d1"
        fields={FIELDS}
        selected="gross_pay"
        editing="gross_pay"
        onEdit={vi.fn()}
      />,
    );
    expect(queryByRole("button", { name: "Edit" })).toBeNull();
  });

  it("does not stop the value's text being selected", () => {
    // The row is clickable, and a processor copying an account number drags
    // across the value. Nothing may call `preventDefault` on that — the click
    // that ends the drag is allowed to select the row, and the browser's own
    // text selection has to survive it.
    const onSelect = vi.fn();
    const { getByText } = render(
      <ReviewerFields documentId="d1" fields={FIELDS} onSelect={onSelect} />,
    );
    const value = getByText("v-gross_pay");
    const event = new MouseEvent("click", { bubbles: true, cancelable: true });
    value.dispatchEvent(event);
    expect(onSelect).toHaveBeenCalledWith("gross_pay");
    expect(event.defaultPrevented, "the row must not swallow the click").toBe(false);
  });
});
