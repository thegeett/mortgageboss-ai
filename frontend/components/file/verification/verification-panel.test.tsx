// @vitest-environment jsdom
import type { VerificationStatus } from "@/lib/types/verification";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const runMutate = vi.fn();
const useVerificationMock = vi.fn();

vi.mock("@/lib/api/verification", () => ({
  useVerification: () => useVerificationMock(),
  useRunVerification: () => ({ mutate: runMutate, isPending: false }),
}));

import { VerificationPanel } from "./verification-panel";

const STATUS: VerificationStatus = {
  stale: false,
  latest_run: {
    id: "run-1",
    status: "completed",
    trigger: "manual",
    started_at: "2026-06-28T10:00:00Z",
    completed_at: "2026-06-28T10:00:05Z",
    red_count: 0,
    yellow_count: 1,
    green_count: 0,
    total_cost_estimate: 0.02,
  },
  findings: [
    {
      id: "f-1",
      rule_id: "cross_source.income_variance",
      origin: "ai_cross_source",
      status: "yellow",
      category: "income",
      message: "Stated income exceeds the documents by 8%.",
      confidence: 0.82,
      source_page: 1,
      source_snippet: "Gross pay 3,775.00 biweekly",
      resolution_status: "open",
      details: {},
    },
  ],
};

function mock(overrides: Partial<ReturnType<typeof useVerificationMock>> = {}) {
  useVerificationMock.mockReturnValue({
    data: STATUS,
    isPending: false,
    isError: false,
    refetch: vi.fn(),
    ...overrides,
  });
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("VerificationPanel", () => {
  it("renders the trigger and the cross-source findings", () => {
    mock();
    render(<VerificationPanel fileId="LF-1" />);

    expect(screen.getByRole("button", { name: /run verification/i })).toBeDefined();
    expect(screen.getByText("Stated income exceeds the documents by 8%.")).toBeDefined();
    expect(screen.getByText(/82.00% confidence/)).toBeDefined();
    expect(screen.getByText(/p\.1/)).toBeDefined();
  });

  it("triggers the pass on click", () => {
    mock();
    render(<VerificationPanel fileId="LF-1" />);
    fireEvent.click(screen.getByRole("button", { name: /run verification/i }));
    expect(runMutate).toHaveBeenCalled();
  });

  it("shows the staleness banner when out of date", () => {
    mock({ data: { ...STATUS, stale: true } });
    render(<VerificationPanel fileId="LF-1" />);
    expect(screen.getByRole("alert")).toBeDefined();
    expect(screen.getByText(/Documents changed/)).toBeDefined();
  });

  it("shows a running state and disables the trigger while a run is in progress", () => {
    const run = STATUS.latest_run ?? null;
    mock({
      data: { ...STATUS, latest_run: run ? { ...run, status: "running" } : null },
    });
    render(<VerificationPanel fileId="LF-1" />);
    expect(screen.getByRole("button", { name: /running/i })).toHaveProperty("disabled", true);
  });

  it("renders the loading skeleton while pending", () => {
    mock({ data: undefined, isPending: true });
    render(<VerificationPanel fileId="LF-1" />);
    expect(screen.getByText("Loading verification")).toBeDefined();
  });

  it("renders an error with retry", () => {
    const refetch = vi.fn();
    mock({ data: undefined, isError: true, refetch });
    render(<VerificationPanel fileId="LF-1" />);
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(refetch).toHaveBeenCalled();
  });
});
