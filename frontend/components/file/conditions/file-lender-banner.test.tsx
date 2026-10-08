// @vitest-environment jsdom
/**
 * LP-949 — the file's lender above the conditions: offered from the sheet, set only on her click,
 * declined on her click, and gone once the file has a lender. LP-965 — it says nothing about code maps.
 */
import type { FileLender, LenderSuggestion } from "@/lib/types/conditions";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({
  data: undefined as FileLender | undefined,
  set: [] as unknown[],
  declined: [] as unknown[],
}));
vi.mock("@/lib/api/conditions", () => ({
  useFileLender: () => ({ data: state.data }),
  useSetFileLender: () => ({ isPending: false, mutate: (b: unknown) => state.set.push(b) }),
  useDeclineFileLender: () => ({
    isPending: false,
    mutate: (b: unknown) => state.declined.push(b),
  }),
}));
vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

import { FileLenderBanner } from "./file-lender-banner";

afterEach(() => {
  cleanup();
  state.set = [];
  state.declined = [];
});

const SUGGESTED: FileLender = {
  lender: null,
  suggestion: {
    round_id: "r2",
    key: "uwm",
    name: "United Wholesale Mortgage",
    source: "reader",
    lender_exists: false,
  },
};

describe("FileLenderBanner", () => {
  it("offers the sheet's lender and sets nothing until she presses the button", () => {
    state.data = SUGGESTED;
    render(<FileLenderBanner fileId="f1" />);
    expect(screen.getByText(/the sheet’s layout/)).toBeTruthy();
    expect(
      screen.getByText(/Setting it also adds United Wholesale Mortgage to your lenders\./),
    ).toBeTruthy();
    expect(state.set).toEqual([]);
    fireEvent.click(
      screen.getByRole("button", { name: "Set United Wholesale Mortgage as the lender" }),
    );
    expect(state.set).toEqual([{ lender_key: "uwm" }]);
    expect(state.declined).toEqual([]);
  });

  it("says nothing about the library, and only adds the lender when it is new", () => {
    state.data = SUGGESTED;
    render(<FileLenderBanner fileId="f1" />);
    expect(screen.queryByText(/library/)).toBeNull();
    expect(screen.queryByText(/condition codes/)).toBeNull();
    cleanup();
    state.data = {
      lender: null,
      suggestion: { ...(SUGGESTED.suggestion as LenderSuggestion), lender_exists: true },
    };
    render(<FileLenderBanner fileId="f1" />);
    expect(screen.queryByText(/to your lenders/)).toBeNull();
  });

  it("declines for the round the suggestion came from", () => {
    state.data = SUGGESTED;
    render(<FileLenderBanner fileId="f1" />);
    fireEvent.click(screen.getByRole("button", { name: "Not this lender" }));
    expect(state.declined).toEqual(["r2"]);
    expect(state.set).toEqual([]);
  });

  it("without a suggestion, points to Overview", () => {
    state.data = { lender: null, suggestion: null };
    render(<FileLenderBanner fileId="f1" />);
    expect(screen.getByText("This file has no lender")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Overview" }).getAttribute("href")).toBe(
      "/loan-files/f1",
    );
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("is gone once the file has a lender, whatever lender it is", () => {
    state.data = { lender: { id: "l1", name: "Small Lender" }, suggestion: null };
    const { container } = render(<FileLenderBanner fileId="f1" />);
    expect(container.innerHTML).toBe("");
  });
});
