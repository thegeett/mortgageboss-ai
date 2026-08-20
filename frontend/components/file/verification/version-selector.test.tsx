// @vitest-environment jsdom
import type { VerificationRun } from "@/lib/types/verification";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const useVerificationRunsMock = vi.fn();
vi.mock("@/lib/api/verification", () => ({
  useVerificationRuns: () => useVerificationRunsMock(),
}));

import { VersionSelector } from "./version-selector";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function run(over: Partial<VerificationRun> = {}): VerificationRun {
  return {
    id: "run-1",
    status: "completed",
    trigger: "manual",
    started_at: "2026-08-19T23:00:00Z",
    completed_at: "2026-08-19T23:06:24Z",
    red_count: 0,
    yellow_count: 5,
    green_count: 0,
    total_cost_estimate: 0.02,
    error_detail: null,
    attention_count: 26,
    satisfied_count: 34,
    cross_check_count: 3,
    ...over,
  };
}

function openHistory(runs: VerificationRun[]) {
  useVerificationRunsMock.mockReturnValue({ data: runs });
  render(<VersionSelector fileId="LF-1" currentRunId="run-1" />);
  fireEvent.click(screen.getByRole("button"));
}

describe("the run history summary (LP-593)", () => {
  it("shows the counts a processor reads on the tab strip, not the legacy severity letters", () => {
    // "5Y" was the LEGACY sweep's yellow count — a colour code needing decoding, naming a different
    // vocabulary from the panel right beside it.
    openHistory([run()]);

    expect(screen.getByText("26")).toBeDefined();
    expect(screen.getByText("34")).toBeDefined();
    expect(screen.getByText("3")).toBeDefined();
    expect(screen.queryByText(/5Y/)).toBeNull();
  });

  it("names each number on hover rather than spelling three labels per row", () => {
    // The list exists to COMPARE runs and pick one, so the figures are what the eye needs; three
    // written labels on every row would wrap the dropdown.
    openHistory([run()]);

    expect(screen.getByTitle("Needs attention").textContent).toBe("26");
    expect(screen.getByTitle("Satisfied").textContent).toBe("34");
    expect(screen.getByTitle("Cross-checks").textContent).toBe("3");
  });

  it("hides a zero rather than printing it", () => {
    openHistory([run({ cross_check_count: 0 })]);

    expect(screen.queryByTitle("Cross-checks")).toBeNull();
    expect(screen.getByTitle("Needs attention")).toBeDefined();
  });

  it("marks a run that produced nothing at all, rather than rendering an empty row", () => {
    openHistory([run({ attention_count: 0, satisfied_count: 0, cross_check_count: 0 })]);

    expect(screen.getByTitle(/produced no findings/i)).toBeDefined();
  });
});
