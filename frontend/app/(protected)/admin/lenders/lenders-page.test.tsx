// @vitest-environment jsdom
import type { OverlayLenderSummary } from "@/lib/types/overlay-admin";
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const useOverlayLenders = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/overlay-admin", () => ({ useOverlayLenders }));

const authState = vi.hoisted(() => ({ role: "admin" as string | undefined }));
vi.mock("@/lib/stores/auth-store", () => ({
  useAuthStore: (selector: (s: unknown) => unknown) => selector({ user: { role: authState.role } }),
}));

import AdminLendersPage from "./page";

afterEach(() => {
  cleanup();
  useOverlayLenders.mockReset();
  authState.role = "admin";
});

function lender(overrides: Partial<OverlayLenderSummary> = {}): OverlayLenderSummary {
  return {
    id: "l1",
    name: "UWM",
    supported_programs: ["conventional"],
    override_count: 0,
    last_changed_at: null,
    ...overrides,
  };
}

function loaded(lenders: OverlayLenderSummary[]) {
  useOverlayLenders.mockReturnValue({
    data: lenders,
    isPending: false,
    isError: false,
    refetch: vi.fn(),
  });
}

describe("Admin lenders list (LP-UI-025)", () => {
  it("leads with the overlay, not the contact details", () => {
    loaded([lender({ override_count: 3 })]);
    render(<AdminLendersPage />);
    expect(screen.getByText("3 rules overridden")).toBeTruthy();
  });

  it("says a lender with no overrides is correct, not empty", () => {
    // Zero is a real answer: the agency guideline applies unchanged here. A bare
    // "0" leaves a reader wondering whether the data failed to load.
    loaded([lender({ override_count: 0 })]);
    render(<AdminLendersPage />);
    expect(screen.getByText("Agency guideline, unchanged")).toBeTruthy();
    expect(screen.queryByText("0 rules overridden")).toBeNull();
  });

  it("distinguishes never edited from edited long ago", () => {
    loaded([
      lender({ id: "a", name: "UWM", last_changed_at: null }),
      lender({ id: "b", name: "Rocket", last_changed_at: "2026-08-01T00:00:00Z" }),
    ]);
    render(<AdminLendersPage />);
    const rows = screen.getAllByRole("row");
    const uwm = rows.find((r) => within(r).queryByText("UWM")) as HTMLElement;
    const rocket = rows.find((r) => within(r).queryByText("Rocket")) as HTMLElement;
    expect(within(uwm).getByText("Never edited")).toBeTruthy();
    expect(within(rocket).queryByText("Never edited")).toBeNull();
  });

  it("says one rule, not one rules", () => {
    loaded([lender({ override_count: 1 })]);
    render(<AdminLendersPage />);
    expect(screen.getByText("1 rule overridden")).toBeTruthy();
  });

  it("links each lender to its overlay editor", () => {
    loaded([lender({ id: "abc" })]);
    render(<AdminLendersPage />);
    expect(screen.getByRole("link", { name: "UWM" }).getAttribute("href")).toBe(
      "/admin/lenders/abc",
    );
  });

  it("tells a non-admin why the page is empty", () => {
    authState.role = "processor";
    loaded([lender()]);
    render(<AdminLendersPage />);
    expect(screen.getByText(/available to admins only/)).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("distinguishes no lenders from a failed load", () => {
    loaded([]);
    render(<AdminLendersPage />);
    expect(screen.getByText(/No lenders configured/)).toBeTruthy();
  });
});
