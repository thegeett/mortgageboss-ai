// @vitest-environment jsdom
import type {
  AggressionLevel,
  VerificationFinding,
  VerificationStatus,
} from "@/lib/types/verification";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const runMutate = vi.fn();
const setAggressionMutate = vi.fn();
const resolveMutate = vi.fn();
const updatePreferencesMutate = vi.fn();
const useVerificationMock = vi.fn();
const useNeedsMock = vi.fn(() => ({ data: [] }));
const invalidateQueries = vi.fn();

vi.mock("@/lib/api/verification", () => ({
  useVerification: () => useVerificationMock(),
  useRunVerification: () => ({ mutate: runMutate, isPending: false }),
  useSetAggression: () => ({ mutate: setAggressionMutate, isPending: false }),
  useResolveFinding: () => ({ mutate: resolveMutate, isPending: false }),
  useVerificationRuns: () => ({ data: [] }),
  verificationQueryKey: (id: string) => ["verification", id],
}));

vi.mock("@/lib/api/needs", () => ({
  useNeeds: () => useNeedsMock(),
}));

vi.mock("@/lib/api/preferences", () => ({
  useUpdatePreferences: () => ({ mutate: updatePreferencesMutate, isPending: false }),
}));

vi.mock("@tanstack/react-query", () => ({
  useQueryClient: () => ({ invalidateQueries }),
}));

import { VerificationPanel } from "./verification-panel";

const CUTOFFS: Record<AggressionLevel, number> = {
  conservative: 0.8,
  balanced: 0.5,
  thorough: 0.0,
};

function finding(over: Partial<VerificationFinding> & { id: string }): VerificationFinding {
  return {
    rule_id: "cross_source.income_variance",
    origin: "ai_cross_source",
    status: "yellow",
    category: "income",
    message: "A discrepancy.",
    confidence: 0.82,
    source_page: 1,
    source_snippet: "Gross pay 3,775.00 biweekly",
    resolution_status: "open",
    resolution_note: null,
    applied_record: null,
    details: {},
    ...over,
  };
}

const STATUS: VerificationStatus = {
  stale: false,
  program: "conventional",
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
    finding({ id: "f-1", message: "Stated income exceeds the documents by 8%.", confidence: 0.82 }),
  ],
  aggression: {
    level: "balanced",
    default: "balanced",
    override: null,
    cutoff: 0.5,
    cutoffs: CUTOFFS,
  },
  blocked: false,
  in_scope_open_count: 0,
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

/** The fixture's run, non-null (biome forbids `!`). */
function baseRun() {
  if (!STATUS.latest_run) throw new Error("fixture must have a run");
  return STATUS.latest_run;
}

afterEach(() => {
  cleanup();
  vi.resetAllMocks(); // resets call history AND any per-test mockImplementation
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

  it("triggers the pass (cached by default) on click", () => {
    mock();
    render(<VerificationPanel fileId="LF-1" />);
    fireEvent.click(screen.getByRole("button", { name: /run verification/i }));
    expect(runMutate).toHaveBeenCalledWith(false); // default: return cached if unchanged
  });

  it("force-reruns via the 'Re-run anyway' escape hatch", () => {
    mock(); // the fixture's latest_run is completed → the escape hatch is shown
    render(<VerificationPanel fileId="LF-1" />);
    fireEvent.click(screen.getByRole("button", { name: /re-run anyway/i }));
    expect(runMutate).toHaveBeenCalledWith(true); // force = bypass the cache
  });

  it("shows the staleness banner when out of date", () => {
    mock({ data: { ...STATUS, stale: true } });
    render(<VerificationPanel fileId="LF-1" />);
    expect(screen.getByRole("alert")).toBeDefined();
    expect(screen.getByText(/The file changed/)).toBeDefined();
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

  it("counts in-scope findings (not the run's per-run counts)", () => {
    // The run claims 5 yellow, but one finding is in scope at Balanced — follow the list.
    mock({ data: { ...STATUS, latest_run: { ...baseRun(), yellow_count: 5 } } });
    render(<VerificationPanel fileId="LF-1" />);
    expect(screen.getByText("1 finding")).toBeDefined();
  });

  it("refreshes the DTI + LTV calculators when a run completes", () => {
    const runningRun = { ...baseRun(), status: "running" as const };
    mock({ data: { ...STATUS, latest_run: runningRun } });
    const { rerender } = render(<VerificationPanel fileId="LF-1" />);
    expect(invalidateQueries).not.toHaveBeenCalled();

    // The poll flips the run to completed → the finding-coupled calculators refresh.
    mock({ data: { ...STATUS, latest_run: { ...runningRun, status: "completed" } } });
    rerender(<VerificationPanel fileId="LF-1" />);

    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: ["dti", "LF-1"] });
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: ["ltv", "LF-1"] });
  });

  // --- The aggression dial (LP-79) ------------------------------------------

  it("renders the dial with the active level pressed", () => {
    mock();
    render(<VerificationPanel fileId="LF-1" />);
    const balanced = screen.getByRole("button", { name: "Balanced" });
    expect(balanced.getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("button", { name: "Thorough" }).getAttribute("aria-pressed")).toBe(
      "false",
    );
  });

  it("moving the dial sets the per-file override — no AI re-run", () => {
    mock();
    render(<VerificationPanel fileId="LF-1" />);
    fireEvent.click(screen.getByRole("button", { name: "Thorough" }));
    // The dial calls setAggression (a read-time re-filter), NOT runVerification (the AI).
    expect(setAggressionMutate).toHaveBeenCalledTimes(1);
    expect(setAggressionMutate.mock.calls[0]?.[0]).toBe("thorough");
    expect(runMutate).not.toHaveBeenCalled();
  });

  it("re-filters instantly: dialing up to Thorough reveals a low-confidence finding", () => {
    mock({
      data: {
        ...STATUS,
        findings: [
          finding({ id: "hi", message: "High-confidence discrepancy.", confidence: 0.9 }),
          finding({ id: "lo", message: "Low-confidence hunch.", confidence: 0.4 }),
        ],
      },
    });
    render(<VerificationPanel fileId="LF-1" />);
    // At Balanced (≥0.5) the 0.4 hunch is hidden.
    expect(screen.queryByText("Low-confidence hunch.")).toBeNull();
    expect(screen.getByText("High-confidence discrepancy.")).toBeDefined();

    // Dialing up to Thorough (≥0.0) surfaces it instantly — same stored findings.
    fireEvent.click(screen.getByRole("button", { name: "Thorough" }));
    expect(screen.getByText("Low-confidence hunch.")).toBeDefined();
    expect(screen.getByText("High-confidence discrepancy.")).toBeDefined();
  });

  it("never recolors: a red finding stays red across dial moves", () => {
    mock({
      data: {
        ...STATUS,
        findings: [finding({ id: "r", status: "red", confidence: 0.9 })],
        latest_run: { ...baseRun(), red_count: 1, yellow_count: 0 },
      },
    });
    render(<VerificationPanel fileId="LF-1" />);
    expect(screen.getByText("1 red")).toBeDefined();
    // Move the dial — the in-scope set may change, but severity is intrinsic.
    fireEvent.click(screen.getByRole("button", { name: "Conservative" }));
    expect(screen.getByText("1 red")).toBeDefined();
  });

  it("shows the legible consequence after moving the dial", () => {
    const data: VerificationStatus = {
      ...STATUS,
      findings: [finding({ id: "hi", confidence: 0.9 }), finding({ id: "lo", confidence: 0.4 })],
    };
    // The mock confirms the override by returning the re-filtered status (the API contract).
    setAggressionMutate.mockImplementation(
      (level: AggressionLevel, opts?: { onSuccess?: (s: VerificationStatus) => void }) => {
        opts?.onSuccess?.({
          ...data,
          aggression: { ...data.aggression, level, override: level, cutoff: CUTOFFS[level] },
        });
      },
    );
    mock({ data });
    render(<VerificationPanel fileId="LF-1" />);
    fireEvent.click(screen.getByRole("button", { name: "Thorough" }));
    // Thorough surfaced the 0.4 finding → the consequence is communicated.
    expect(screen.getByText(/Thorough surfaced 1 more finding/)).toBeDefined();
  });

  it("reset-to-default clears the per-file override", () => {
    mock({
      data: {
        ...STATUS,
        aggression: { ...STATUS.aggression, level: "thorough", override: "thorough", cutoff: 0.0 },
      },
    });
    render(<VerificationPanel fileId="LF-1" />);
    fireEvent.click(screen.getByRole("button", { name: /reset to default/i }));
    expect(setAggressionMutate.mock.calls[0]?.[0]).toBeNull(); // null = revert to user default
  });

  it("'set as my default' updates the user-level preference", () => {
    mock({
      data: {
        ...STATUS,
        aggression: { ...STATUS.aggression, level: "thorough", override: "thorough", cutoff: 0.0 },
      },
    });
    render(<VerificationPanel fileId="LF-1" />);
    fireEvent.click(screen.getByRole("button", { name: /set thorough as my default/i }));
    expect(updatePreferencesMutate.mock.calls[0]?.[0]).toBe("thorough");
  });

  it("shows the blocked submit status with the active thoroughness", () => {
    mock({ data: { ...STATUS, blocked: true, in_scope_open_count: 2 } });
    render(<VerificationPanel fileId="LF-1" />);
    expect(
      screen.getByText(/must be resolved to submit \(at Balanced thoroughness\)/),
    ).toBeDefined();
  });
});
