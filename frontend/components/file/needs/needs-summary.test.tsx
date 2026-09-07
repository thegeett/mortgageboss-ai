// @vitest-environment jsdom
import type { NeedsItemPublic } from "@/lib/types/needs-item";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const useNeeds = vi.hoisted(() => vi.fn());
const useLoanFileDocuments = vi.hoisted(() => vi.fn(() => ({ data: [] })));
vi.mock("@/lib/api/needs", () => ({ useNeeds }));
vi.mock("@/lib/api/documents", () => ({ useLoanFileDocuments }));

import { NeedsSummary } from "./needs-summary";

afterEach(() => {
  cleanup();
  useNeeds.mockReset();
});

function need(overrides: Partial<NeedsItemPublic> = {}): NeedsItemPublic {
  return {
    id: "n1",
    title: "Most recent pay stub",
    needs_type: "pay_stub",
    status: "pending",
    priority: "standard",
    source_attribution: "baseline",
    ...(overrides as Partial<NeedsItemPublic>),
  } as NeedsItemPublic;
}

function loaded(items: NeedsItemPublic[]) {
  useNeeds.mockReturnValue({ data: items, isPending: false, isError: false });
}

describe("NeedsSummary (LP-UI-022)", () => {
  it("counts by the same grouping the list uses", () => {
    // A summary that counted its own way is the LP-UI-013 defect: this number
    // and the list one click away must not be able to disagree.
    loaded([
      need({ id: "a", status: "pending" }),
      need({ id: "b", status: "requested" }),
      need({ id: "c", status: "verified" }),
    ]);
    render(<NeedsSummary fileId="LF-1" />);
    // pending + requested both group as "needs action"; verified is complete.
    const action = screen.getByText("Needs action").closest("a") as HTMLElement;
    expect(action.textContent).toContain("2");
  });

  it("links every count through to the needs route", () => {
    loaded([need()]);
    render(<NeedsSummary fileId="LF-1" />);
    for (const link of screen.getAllByRole("link")) {
      expect(link.getAttribute("href")).toBe("/loan-files/LF-1/needs");
    }
  });

  it("calls out proposals separately from the chase pile", () => {
    // An AI proposal is never acted on until a processor confirms it, so it is
    // not work to chase — it is work to decide.
    // `isProposed` reads `disposition`, not `source_attribution` — a fixture
    // using the wrong field type-checks and describes a need the product never
    // produces.
    loaded([need({ id: "p", status: "pending", disposition: "proposed" })]);
    render(<NeedsSummary fileId="LF-1" />);
    expect(screen.getByText("1 to review")).toBeTruthy();
  });

  it("says nothing about proposals when there are none", () => {
    loaded([need()]);
    render(<NeedsSummary fileId="LF-1" />);
    expect(screen.queryByText(/to review/)).toBeNull();
    // Positive control: the summary rendered, so the absence above is real.
    expect(screen.getByText("Needs action")).toBeTruthy();
  });

  it("degrades on a file with no needs yet", () => {
    loaded([]);
    render(<NeedsSummary fileId="LF-1" />);
    expect(screen.getByText(/No needs yet/)).toBeTruthy();
  });

  it("does not show a stale count while loading", () => {
    useNeeds.mockReturnValue({ data: undefined, isPending: true, isError: false });
    render(<NeedsSummary fileId="LF-1" />);
    expect(screen.getByText("Loading the needs summary")).toBeTruthy();
    expect(screen.queryByText("Needs action")).toBeNull();
  });
});
