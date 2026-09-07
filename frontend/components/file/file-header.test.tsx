// @vitest-environment jsdom
/**
 * The identity strip's named criterion, on the rendered component.
 *
 * The ticket's own measurement — skeleton 54px vs loaded 54.4px — was made in a
 * browser and took four attempts, three of which produced a number that looked
 * like a result and was not. That measurement is the browser's job and this is
 * not a re-run of it: jsdom has no layout. What this pins is the MECHANISM the
 * measurement confirmed — both states are the same element with the same
 * min-height — which is the thing an edit would break.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render as rtlRender, screen } from "@testing-library/react";
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  usePathname: () => "/loan-files/LF-1234",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

import { FileHeader } from "./file-header";

const FILE = {
  id: "u-1",
  display_id: "LF-1234",
  status: "in_processing",
  loan_program: "conventional",
  loan_purpose: "purchase",
  loan_amount: "450000.00",
  lender_id: null,
  lender_name: "Acme Lending",
  property_address: "123 Main St",
  primary_borrower_name: "Mahesh Chhotala",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-06-20T00:00:00Z",
  attention: null,
} as never;

afterEach(cleanup);

/** The header pulls a delete dialog and other cached bits; give it a client. */
function render(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return rtlRender(React.createElement(QueryClientProvider, { client }, ui));
}

/** The outer strip — the element whose height the criterion is about. */
function strip(container: HTMLElement): HTMLElement {
  const found = container.querySelector<HTMLElement>('[class*="min-h-"]');
  if (!found) throw new Error("the identity strip lost its min-height");
  return found;
}

describe("FileHeader", () => {
  it("reserves the same height loading as loaded", () => {
    // The skeleton and the file are the same strip with the same floor. Give
    // either branch its own wrapper and the header changes height on resolve,
    // which is the jump the ticket measured and fixed.
    const loading = render(<FileHeader file={undefined} />);
    const loadingClass = strip(loading.container).className;
    cleanup();
    const loaded = render(<FileHeader file={FILE} />);

    expect(strip(loaded.container).className).toBe(loadingClass);
    expect(loadingClass).toContain("min-h-");
  });

  it("names a file with no borrower rather than showing its id", () => {
    render(<FileHeader file={{ ...(FILE as object), primary_borrower_name: null } as never} />);
    expect(screen.getByText("Unnamed file")).toBeDefined();
  });

  it("shows the borrower when there is one", () => {
    render(<FileHeader file={FILE} />);
    expect(screen.getByText("Mahesh Chhotala")).toBeDefined();
  });
});
