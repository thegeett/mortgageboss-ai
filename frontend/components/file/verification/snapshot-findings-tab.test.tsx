// @vitest-environment jsdom
import type { SnapshotFinding } from "@/lib/types/verification";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const useSnapshotFindingsMock = vi.fn();
const setDispositionMock = vi.fn();
vi.mock("@/lib/api/verification", () => ({
  useSnapshotFindings: () => useSnapshotFindingsMock(),
  useSetSnapshotFindingDisposition: () => ({ mutate: setDispositionMock, isPending: false }),
}));

import { SnapshotFindingsTab } from "./snapshot-findings-tab";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function finding(over: Partial<SnapshotFinding> = {}): SnapshotFinding {
  return {
    id: "sf-1",
    kind: "valuation_vs_assessment",
    title: "The tax assessment sits below the stated valuation",
    detail: "The application states 578,000; the county assessed 551,923 for tax year 2024.",
    sources: [
      { label: "application", value: "578,000.00" },
      { label: "property tax bill", value: "551,923" },
    ],
    disposition: "open",
    disposition_note: null,
    first_seen_at: "2026-08-19T23:00:00Z",
    last_seen_at: "2026-08-19T23:00:00Z",
    ...over,
  };
}

function mock(data: SnapshotFinding[] | undefined, extra: Record<string, unknown> = {}) {
  useSnapshotFindingsMock.mockReturnValue({
    data,
    isPending: false,
    isError: false,
    refetch: vi.fn(),
    ...extra,
  });
}

describe("the cross-source tab", () => {
  it("shows BOTH sides of the comparison, which is what makes it checkable", () => {
    // A cross-source finding a processor cannot check without reopening every document is just a
    // sentence. The two figures side by side ARE the finding.
    mock([finding()]);
    render(<SnapshotFindingsTab fileId="LF-1" />);

    expect(screen.getByText("application")).toBeDefined();
    expect(screen.getByText("578,000.00")).toBeDefined();
    expect(screen.getByText("property tax bill")).toBeDefined();
    expect(screen.getByText("551,923")).toBeDefined();
  });

  it("offers no Apply — this pass may not write to the loan", () => {
    // THE SAFETY PROPERTY. No rule spec, no calibrated threshold, no guideline citation, so there is
    // no basis for changing a number off it. Sign off and dismiss record a decision; neither touches
    // the file. A regression that added an Apply here would be a real one.
    mock([finding()]);
    render(<SnapshotFindingsTab fileId="LF-1" />);

    expect(screen.queryByRole("button", { name: /apply/i })).toBeNull();
    expect(screen.getByRole("button", { name: /sign off/i })).toBeDefined();
    expect(screen.getByRole("button", { name: /not an issue/i })).toBeDefined();
  });

  it("records a sign-off without changing the loan", () => {
    mock([finding()]);
    render(<SnapshotFindingsTab fileId="LF-1" />);

    fireEvent.click(screen.getByRole("button", { name: /sign off/i }));

    expect(setDispositionMock).toHaveBeenCalledWith({
      findingId: "sf-1",
      disposition: "signed_off",
    });
  });

  it("says a finding was resolved by a file change, rather than dropping it silently", () => {
    // The feedback that a processor's work landed. Silent disappearance is indistinguishable from a
    // bug, which is why this state exists at all.
    mock([finding({ disposition: "resolved" })]);
    render(<SnapshotFindingsTab fileId="LF-1" />);

    expect(screen.getByText(/resolved by a file change/i)).toBeDefined();
  });

  it("will not let a processor reopen a resolved finding", () => {
    // `resolved` is the SYSTEM's label — set because the file stopped producing the finding. A person
    // claiming otherwise would make the tab lie about WHY something cleared. Their own dispositions
    // are reopenable; this one is not.
    mock([finding({ disposition: "resolved" })]);
    render(<SnapshotFindingsTab fileId="LF-1" />);

    expect(screen.queryByRole("button", { name: /reopen/i })).toBeNull();
  });

  it("lets a processor reopen their OWN disposition", () => {
    mock([finding({ disposition: "signed_off" })]);
    render(<SnapshotFindingsTab fileId="LF-1" />);

    fireEvent.click(screen.getByRole("button", { name: /reopen/i }));

    expect(setDispositionMock).toHaveBeenCalledWith({ findingId: "sf-1", disposition: "open" });
  });

  it("says an empty list means nothing to reconcile, not nothing looked at", () => {
    mock([]);
    render(<SnapshotFindingsTab fileId="LF-1" />);

    expect(screen.getByText(/no cross-source pairings found/i)).toBeDefined();
    expect(screen.getByText(/not that nothing was looked at/i)).toBeDefined();
  });
});
