// @vitest-environment jsdom
import type { ParseWarning } from "@/lib/types/stated-financials";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const useStatedFinancials = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/mismo", () => ({ useStatedFinancials }));

import { MismoWarnings } from "./mismo-warnings";

afterEach(() => {
  cleanup();
  useStatedFinancials.mockReset();
});

function withWarnings(warnings: ParseWarning[]) {
  useStatedFinancials.mockReturnValue({
    data: {
      borrowers: [],
      liabilities: [],
      assets: [],
      loan_terms: {},
      property_extras: null,
      mismo_import: {
        source_format: "xml",
        status: warnings.length > 0 ? "partial" : "completed",
        warnings,
        imported_at: "2026-06-12T00:00:00Z",
      },
    },
    isPending: false,
    isError: false,
  });
}

describe("MismoWarnings (LP-UI-024)", () => {
  it("shows the warnings after the toast is gone", () => {
    // "Imported with 6 fields to review" was a toast, and a toast is gone by the
    // time a processor is looking at the thing it described.
    withWarnings([
      { message: "Subject property is missing an estimated value.", subject: "property" },
    ]);
    render(<MismoWarnings fileId="LF-1" />);
    expect(screen.getByText(/Subject property is missing an estimated value/)).toBeTruthy();
  });

  it("links each warning to the section it concerns", () => {
    withWarnings([
      { message: "Loan is missing a base loan amount.", subject: "loan" },
      { message: "Borrower #1 is missing a name.", subject: "borrowers" },
    ]);
    render(<MismoWarnings fileId="LF-1" />);
    expect(screen.getByRole("link", { name: /Go to the loan/ }).getAttribute("href")).toBe(
      "#card-loan",
    );
    expect(screen.getByRole("link", { name: /Go to borrowers/ }).getAttribute("href")).toBe(
      "#card-borrowers",
    );
  });

  it("renders nothing at all when the import was clean", () => {
    // Not an empty panel: a heading saying a clean import had nothing wrong with
    // it is a permanent reminder of a non-event.
    withWarnings([]);
    const { container } = render(<MismoWarnings fileId="LF-1" />);
    expect(container.firstChild).toBeNull();
  });

  it("renders nothing for a file that was never imported", () => {
    useStatedFinancials.mockReturnValue({ data: undefined, isPending: false, isError: false });
    const { container } = render(<MismoWarnings fileId="LF-1" />);
    expect(container.firstChild).toBeNull();
  });

  it("still shows a warning it cannot place, without a dead link", () => {
    // `other` is a real subject, not a gap — including a legacy row stored before
    // subjects existed, which reads as `other`. It must appear; it must not offer
    // a link to nowhere.
    withWarnings([{ message: "Something the parser could not attribute.", subject: "other" }]);
    render(<MismoWarnings fileId="LF-1" />);
    expect(screen.getByText(/could not attribute/)).toBeTruthy();
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("counts the fields to review", () => {
    withWarnings([
      { message: "a", subject: "loan" },
      { message: "b", subject: "property" },
    ]);
    render(<MismoWarnings fileId="LF-1" />);
    expect(screen.getByText("2 fields to review")).toBeTruthy();
  });
});
