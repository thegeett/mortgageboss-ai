// @vitest-environment jsdom
import type {
  AggressionLevel,
  VerificationFinding,
  VerificationStatus,
} from "@/lib/types/verification";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const resolveMutate = vi.fn();
vi.mock("@/lib/api/verification", () => ({
  useResolveFinding: () => ({ mutate: resolveMutate, isPending: false }),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { FindingsList } from "./findings-list";

const CUTOFFS: Record<AggressionLevel, number> = {
  conservative: 0.8,
  balanced: 0.5,
  thorough: 0.0,
};

function finding(over: Partial<VerificationFinding> & { id: string }): VerificationFinding {
  return {
    rule_id: "cross_source.liability_discrepancy",
    origin: "ai_cross_source",
    status: "yellow",
    category: "credit",
    message: "An undisclosed obligation.",
    confidence: 0.9,
    source_page: null,
    source_snippet: null,
    resolution_status: "open",
    resolution_note: null,
    details: { apply: { action: "add_liability" } },
    ...over,
  };
}

function status(findings: VerificationFinding[]): VerificationStatus {
  return {
    stale: false,
    latest_run: {
      id: "r",
      status: "completed",
      trigger: "manual",
      started_at: null,
      completed_at: null,
      red_count: 0,
      yellow_count: findings.length,
      green_count: 0,
      total_cost_estimate: null,
    },
    findings,
    aggression: {
      level: "balanced",
      default: "balanced",
      override: null,
      cutoff: 0.5,
      cutoffs: CUTOFFS,
    },
    blocked: false,
    in_scope_open_count: findings.length,
  };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("FindingsList", () => {
  it("dial cutoff hides low-confidence open findings; dialing up reveals them", () => {
    const data = status([
      finding({ id: "hi", message: "High-confidence.", confidence: 0.9 }),
      finding({ id: "lo", message: "Low-confidence hunch.", confidence: 0.3 }),
    ]);
    const { rerender } = render(<FindingsList fileId="LF-1" data={data} activeLevel="balanced" />);
    expect(screen.queryByText("Low-confidence hunch.")).toBeNull();

    rerender(<FindingsList fileId="LF-1" data={data} activeLevel="thorough" />);
    expect(screen.getByText("Low-confidence hunch.")).toBeDefined();
  });

  it("resolved findings appear in a 'Resolved' group (never silently dropped)", () => {
    const data = status([
      finding({ id: "open" }),
      finding({ id: "done", resolution_status: "applied", message: "Applied one." }),
    ]);
    render(<FindingsList fileId="LF-1" data={data} activeLevel="balanced" />);
    expect(screen.getByText(/Resolved · 1/)).toBeDefined();
  });

  it("Apply on an open finding fires the resolve mutation", () => {
    render(
      <FindingsList fileId="LF-1" data={status([finding({ id: "x" })])} activeLevel="balanced" />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(resolveMutate).toHaveBeenCalledTimes(1);
    expect(resolveMutate.mock.calls[0]?.[0]).toEqual({ kind: "apply", findingId: "x" });
  });
});
