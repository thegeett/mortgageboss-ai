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
import { cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const detail = vi.hoisted(() => ({ data: undefined as unknown }));
vi.mock("@/lib/api/documents", () => ({
  useDocumentDetail: () => ({ ...detail, isPending: false, isError: false }),
}));

import { ReviewerFields } from "./reviewer-fields";

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
    const { rerender } = render(<ReviewerFields documentId="d1" selected={null} />);
    expect(scrolls).toHaveLength(0);

    rerender(<ReviewerFields documentId="d1" selected="net_pay" />);
    expect(scrolls).toHaveLength(1);
  });

  it("uses `nearest`, so a row already on screen does not move", () => {
    // Clicking a row directly must not scroll the list out from under the
    // pointer — `nearest` is a no-op for anything already visible.
    const { rerender } = render(<ReviewerFields documentId="d1" selected={null} />);
    rerender(<ReviewerFields documentId="d1" selected="gross_pay" />);
    expect(scrolls[0]?.block).toBe("nearest");
  });

  it("does not scroll when nothing is selected", () => {
    render(<ReviewerFields documentId="d1" selected={null} />);
    expect(scrolls).toHaveLength(0);
  });

  it("follows the selection as it moves between fields", () => {
    const { rerender } = render(<ReviewerFields documentId="d1" selected="employer_name" />);
    rerender(<ReviewerFields documentId="d1" selected="pay_date" />);
    rerender(<ReviewerFields documentId="d1" selected="net_pay" />);
    expect(scrolls.length).toBeGreaterThanOrEqual(3);
  });
});
