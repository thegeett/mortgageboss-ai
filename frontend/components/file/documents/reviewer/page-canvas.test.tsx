// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const image = vi.hoisted(() => ({
  value: { data: undefined as unknown, isPending: false, isError: false },
}));
vi.mock("@/lib/api/page-image", () => ({ usePageImage: () => image.value }));

import { PageCanvas } from "./page-canvas";

afterEach(() => {
  cleanup();
  image.value = { data: undefined, isPending: false, isError: false };
});

const PAGE = { url: "blob:x", widthPoints: 612, heightPoints: 792, zoom: 2, pageCount: 3 };

/**
 * A page that will not draw says so (LP-UI-030, fixed after a report from the app).
 *
 * The fetch failing had a state; the IMAGE failing did not. A dead object url or
 * a truncated render drew the browser's broken-image icon — a grey box with a
 * torn corner, which tells a processor nothing and looks like the app is broken
 * rather than like this document has no page.
 */
describe("PageCanvas", () => {
  it("renders the page when it loads", () => {
    image.value = { data: PAGE, isPending: false, isError: false };
    render(<PageCanvas documentId="d1" page={1} pageCount={3} onPageChange={vi.fn()} />);
    expect(screen.getByRole("img", { name: /page 1/i })).toBeTruthy();
  });

  it("replaces a broken image with the no-page explanation", () => {
    image.value = { data: PAGE, isPending: false, isError: false };
    render(<PageCanvas documentId="d1" page={1} pageCount={3} onPageChange={vi.fn()} />);
    fireEvent.error(screen.getByRole("img", { name: /page 1/i }));
    expect(screen.queryByRole("img")).toBeNull();
    expect(screen.getByText(/No page image for this document/)).toBeTruthy();
  });

  it("gives the next page a fresh chance after one fails", () => {
    // A sticky failure would black out the rest of the document because one page
    // did not draw.
    image.value = { data: PAGE, isPending: false, isError: false };
    const { rerender } = render(
      <PageCanvas documentId="d1" page={1} pageCount={3} onPageChange={vi.fn()} />,
    );
    fireEvent.error(screen.getByRole("img", { name: /page 1/i }));
    expect(screen.queryByRole("img")).toBeNull();

    rerender(<PageCanvas documentId="d1" page={2} pageCount={3} onPageChange={vi.fn()} />);
    expect(screen.getByRole("img", { name: /page 2/i })).toBeTruthy();
  });

  it("gives a different document a fresh chance too", () => {
    image.value = { data: PAGE, isPending: false, isError: false };
    const { rerender } = render(
      <PageCanvas documentId="d1" page={1} pageCount={3} onPageChange={vi.fn()} />,
    );
    fireEvent.error(screen.getByRole("img", { name: /page 1/i }));
    rerender(<PageCanvas documentId="d2" page={1} pageCount={3} onPageChange={vi.fn()} />);
    expect(screen.getByRole("img", { name: /page 1/i })).toBeTruthy();
  });

  describe("the pager says how far there is to go", () => {
    it("names the total, so a reader knows where they are", () => {
      image.value = { data: PAGE, isPending: false, isError: false };
      render(<PageCanvas documentId="d1" page={1} pageCount={3} onPageChange={vi.fn()} />);
      expect(screen.getByText("Page 1 of 3")).toBeTruthy();
    });

    it("will not go past the last page", () => {
      // Offering a Next that renders nothing is the failure this replaces: the
      // reader clicks it, the page goes blank, and nothing says why.
      image.value = { data: PAGE, isPending: false, isError: false };
      render(<PageCanvas documentId="d1" page={3} pageCount={3} onPageChange={vi.fn()} />);
      expect(screen.getByRole("button", { name: "Next page" }).hasAttribute("disabled")).toBe(true);
    });

    it("will not go before the first", () => {
      image.value = { data: PAGE, isPending: false, isError: false };
      render(<PageCanvas documentId="d1" page={1} pageCount={3} onPageChange={vi.fn()} />);
      expect(screen.getByRole("button", { name: "Previous page" }).hasAttribute("disabled")).toBe(
        true,
      );
    });

    it("guards only the lower bound when the total is unknown", () => {
      // `null` means "not told" — a count of zero would be a claim, and the
      // count arrives with page 1 rather than before it.
      image.value = { data: PAGE, isPending: false, isError: false };
      render(<PageCanvas documentId="d1" page={2} pageCount={null} onPageChange={vi.fn()} />);
      expect(screen.getByText("Page 2")).toBeTruthy();
      expect(screen.getByRole("button", { name: "Next page" }).hasAttribute("disabled")).toBe(
        false,
      );
    });
  });

  it("still explains a fetch that failed", () => {
    image.value = { data: undefined, isPending: false, isError: true };
    render(<PageCanvas documentId="d1" page={1} pageCount={null} onPageChange={vi.fn()} />);
    expect(screen.getByText(/No page image for this document/)).toBeTruthy();
  });

  it("does not describe the page's contents in its alt text", () => {
    // It is an image of a borrower's document; describing it would transcribe
    // PII into the accessibility tree. The fields panel is the readable form.
    image.value = { data: PAGE, isPending: false, isError: false };
    render(<PageCanvas documentId="d1" page={1} pageCount={3} onPageChange={vi.fn()} />);
    expect(screen.getByRole("img").getAttribute("alt")).toBe("Page 1 of the document");
  });
});
