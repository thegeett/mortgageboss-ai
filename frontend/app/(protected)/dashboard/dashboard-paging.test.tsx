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

const files = vi.hoisted(() =>
  Array.from({ length: 20 }, (_, i) => ({
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
