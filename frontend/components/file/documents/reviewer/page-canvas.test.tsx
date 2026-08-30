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

/** Every render needs the zoom pair; only the tests about zoom care what it is. */
function canvas(props: Partial<Parameters<typeof PageCanvas>[0]> = {}) {
  return (
    <PageCanvas
      documentId="d1"
      page={1}
      pageCount={3}
      onPageChange={vi.fn()}
      zoom={1}
      onZoomChange={vi.fn()}
      {...props}
    />
  );
}

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
    render(canvas({ documentId: "d1", page: 1, pageCount: 3 }));
    expect(screen.getByRole("img", { name: /page 1/i })).toBeTruthy();
  });

  it("replaces a broken image with the no-page explanation", () => {
    image.value = { data: PAGE, isPending: false, isError: false };
    render(canvas({ documentId: "d1", page: 1, pageCount: 3 }));
    fireEvent.error(screen.getByRole("img", { name: /page 1/i }));
    expect(screen.queryByRole("img")).toBeNull();
    expect(screen.getByText(/No page image for this document/)).toBeTruthy();
  });

  it("gives the next page a fresh chance after one fails", () => {
    // A sticky failure would black out the rest of the document because one page
    // did not draw.
    image.value = { data: PAGE, isPending: false, isError: false };
    const { rerender } = render(canvas({ documentId: "d1", page: 1, pageCount: 3 }));
    fireEvent.error(screen.getByRole("img", { name: /page 1/i }));
    expect(screen.queryByRole("img")).toBeNull();

    rerender(canvas({ documentId: "d1", page: 2, pageCount: 3 }));
    expect(screen.getByRole("img", { name: /page 2/i })).toBeTruthy();
  });

  it("gives a different document a fresh chance too", () => {
    image.value = { data: PAGE, isPending: false, isError: false };
    const { rerender } = render(canvas({ documentId: "d1", page: 1, pageCount: 3 }));
    fireEvent.error(screen.getByRole("img", { name: /page 1/i }));
    rerender(canvas({ documentId: "d2", page: 1, pageCount: 3 }));
    expect(screen.getByRole("img", { name: /page 1/i })).toBeTruthy();
  });

  describe("the pager says how far there is to go", () => {
    it("names the total, so a reader knows where they are", () => {
      image.value = { data: PAGE, isPending: false, isError: false };
      render(canvas({ documentId: "d1", page: 1, pageCount: 3 }));
      expect(screen.getByText("Page 1 of 3")).toBeTruthy();
    });

    it("will not go past the last page", () => {
      // Offering a Next that renders nothing is the failure this replaces: the
      // reader clicks it, the page goes blank, and nothing says why.
      image.value = { data: PAGE, isPending: false, isError: false };
      render(canvas({ documentId: "d1", page: 3, pageCount: 3 }));
      expect(screen.getByRole("button", { name: "Next page" }).hasAttribute("disabled")).toBe(true);
    });

    it("will not go before the first", () => {
      image.value = { data: PAGE, isPending: false, isError: false };
      render(canvas({ documentId: "d1", page: 1, pageCount: 3 }));
      expect(screen.getByRole("button", { name: "Previous page" }).hasAttribute("disabled")).toBe(
        true,
      );
    });

    it("guards only the lower bound when the total is unknown", () => {
      // `null` means "not told" — a count of zero would be a claim, and the
      // count arrives with page 1 rather than before it.
      image.value = { data: PAGE, isPending: false, isError: false };
      render(canvas({ documentId: "d1", page: 2, pageCount: null }));
      expect(screen.getByText("Page 2")).toBeTruthy();
      expect(screen.getByRole("button", { name: "Next page" }).hasAttribute("disabled")).toBe(
        false,
      );
    });
  });

  describe("zoom", () => {
    it("shows the current zoom and offers both directions", () => {
      image.value = { data: PAGE, isPending: false, isError: false };
      render(canvas({ zoom: 1 }));
      expect(screen.getByText("100%")).toBeTruthy();
      expect(screen.getByRole("button", { name: "Zoom in" }).hasAttribute("disabled")).toBe(false);
      expect(screen.getByRole("button", { name: "Zoom out" }).hasAttribute("disabled")).toBe(false);
    });

    it("steps rather than jumping to an arbitrary number", () => {
      image.value = { data: PAGE, isPending: false, isError: false };
      const onZoomChange = vi.fn();
      render(canvas({ zoom: 1, onZoomChange }));
      fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
      expect(onZoomChange).toHaveBeenCalledWith(1.25);
      fireEvent.click(screen.getByRole("button", { name: "Zoom out" }));
      expect(onZoomChange).toHaveBeenLastCalledWith(0.75);
    });

    it("stops at each end", () => {
      image.value = { data: PAGE, isPending: false, isError: false };
      const { rerender } = render(canvas({ zoom: 2 }));
      expect(screen.getByRole("button", { name: "Zoom in" }).hasAttribute("disabled")).toBe(true);
      rerender(canvas({ zoom: 0.5 }));
      expect(screen.getByRole("button", { name: "Zoom out" }).hasAttribute("disabled")).toBe(true);
    });

    it("resets to fit from the readout, which is disabled when already there", () => {
      image.value = { data: PAGE, isPending: false, isError: false };
      const onZoomChange = vi.fn();
      const { rerender } = render(canvas({ zoom: 1.5, onZoomChange }));
      fireEvent.click(screen.getByRole("button", { name: /Zoom is 150%/ }));
      expect(onZoomChange).toHaveBeenCalledWith(1);
      rerender(canvas({ zoom: 1, onZoomChange }));
      expect(screen.getByRole("button", { name: /Zoom is 100%/ }).hasAttribute("disabled")).toBe(
        true,
      );
    });

    it("scales the image's own box, so the highlight boxes come with it", () => {
      // The overlay is positioned in percentages of this element (LP-UI-031), so
      // scaling the wrapper scales the boxes exactly. Sizing the IMAGE instead
      // would leave the overlay behind at the old size.
      image.value = { data: PAGE, isPending: false, isError: false };
      render(canvas({ zoom: 1.5 }));
      const wrapper = screen.getByRole("img").parentElement;
      // Whitespace-insensitive: jsdom reserialises calc() without the spaces.
      const width = (wrapper?.style.width ?? "").replace(/\s+/g, "");
      expect(width).toBe("calc(min(100%,46rem)*1.5)");
    });
  });

  it("still explains a fetch that failed", () => {
    image.value = { data: undefined, isPending: false, isError: true };
    render(canvas({ documentId: "d1", page: 1, pageCount: null }));
    expect(screen.getByText(/No page image for this document/)).toBeTruthy();
  });

  it("does not describe the page's contents in its alt text", () => {
    // It is an image of a borrower's document; describing it would transcribe
    // PII into the accessibility tree. The fields panel is the readable form.
    image.value = { data: PAGE, isPending: false, isError: false };
    render(canvas({ documentId: "d1", page: 1, pageCount: 3 }));
    expect(screen.getByRole("img").getAttribute("alt")).toBe("Page 1 of the document");
  });
});
