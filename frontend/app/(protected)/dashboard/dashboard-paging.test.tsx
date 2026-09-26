// @vitest-environment jsdom
/**
 * The dashboard resets to page 1 when the FILTER changes — any part of it.
 *
 * `setPage(1)` was keyed on the search string alone, so switching saved views or
 * statuses from page 3 left `page` at 3: the table came back empty under
 * "Showing 41–60 of 2". Asserted on the rendered page, not on the reset logic.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const params = vi.hoisted(() => ({ current: new URLSearchParams() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => params.current,
}));

// ⚠️ THREE ROWS, NOT TWENTY, AND THE PAGE LABEL DOES NOT COME FROM THIS LIST. "Page 1 / 3" is
// derived from `total` and `page_size` below, so the row count changes nothing any test here
// asserts — all three check only `pageLabel()`. Twenty rows bought nothing but render time, and
// this file is synchronous: no `waitFor`, no `findBy`. It was costing 3.0-3.3s per test on an idle
// Raspberry Pi against vitest's unconfigured 5000ms default, and 6.7-9.9s under the full suite's
// parallel workers, where it FAILED (LP-909 §5, measured on two machines' worth of load).
//
// Rendering the real `DashboardPage` is still the point — "asserted on the rendered page, not on
// the reset logic" — and three rows render it just as truly as twenty.
const files = vi.hoisted(() =>
  Array.from({ length: 3 }, (_, i) => ({
    id: `u-${i}`,
    display_id: `LF-${1000 + i}`,
    status: "in_processing",
    loan_program: "conventional",
    loan_purpose: "purchase",
    loan_amount: null,
    lender_id: null,
    lender_name: null,
    property_address: null,
    primary_borrower_name: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    attention: null,
  })),
);
vi.mock("@/lib/api/loan-files", () => ({
  useLoanFiles: () => ({
    data: { items: files, total: 60, page: 1, page_size: 20 },
    isPending: false,
    isError: false,
  }),
}));
vi.mock("@/lib/stores/auth-store", () => ({ useAuthStore: () => "Pat" }));
vi.mock("@/components/file/delete-file-dialog", () => ({ DeleteFileDialog: () => null }));

import DashboardPage from "./page";

afterEach(() => {
  cleanup();
  params.current = new URLSearchParams();
});

const pageLabel = () => screen.getByText(/^Page \d+ \/ \d+$/).textContent ?? "";

describe("dashboard paging", () => {
  it("goes back to page 1 when the STATUS filter changes", () => {
    const { rerender } = render(<DashboardPage />);
    fireEvent.click(screen.getByRole("button", { name: /next/i }));
    expect(pageLabel()).toContain("Page 2");

    params.current = new URLSearchParams("status=draft");
    rerender(<DashboardPage />);

    expect(pageLabel()).toContain("Page 1");
  });

  it("goes back to page 1 when a saved VIEW is selected", () => {
    const { rerender } = render(<DashboardPage />);
    fireEvent.click(screen.getByRole("button", { name: /next/i }));
    expect(pageLabel()).toContain("Page 2");

    params.current = new URLSearchParams("view=abc&status=closed");
    rerender(<DashboardPage />);

    expect(pageLabel()).toContain("Page 1");
  });

  it("stays put when the URL has not actually changed", () => {
    // The reset must key on the filter's VALUE, not on a new object identity —
    // otherwise every render sends the reader back to page 1.
    const { rerender } = render(<DashboardPage />);
    fireEvent.click(screen.getByRole("button", { name: /next/i }));

    params.current = new URLSearchParams();
    rerender(<DashboardPage />);

    expect(pageLabel()).toContain("Page 2");
  });
});
