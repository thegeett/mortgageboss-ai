// @vitest-environment jsdom
import type { AggressionLevel, VerificationStatus } from "@/lib/types/verification";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const useNeedsMock = vi.fn(() => ({ data: [] }));
vi.mock("@/lib/api/needs", () => ({ useNeeds: () => useNeedsMock() }));
vi.mock("@/lib/loan-files/needs", () => ({ outstandingNeedsCount: () => 2 }));

import { VerificationStats } from "./verification-stats";

const CUTOFFS: Record<AggressionLevel, number> = { conservative: 0.8, balanced: 0.5, thorough: 0 };

function status(): VerificationStatus {
  return {
    stale: false,
    program: "fha",
    latest_run: null,
    findings: [
      { id: "a", status: "red", resolution_status: "open", confidence: 0.9 },
      { id: "b", status: "yellow", resolution_status: "open", confidence: 0.9 },
      { id: "c", status: "yellow", resolution_status: "open", confidence: 0.2 }, // below cutoff
      { id: "d", status: "red", resolution_status: "overridden", confidence: 0.9 }, // resolved
      // biome-ignore lint/suspicious/noExplicitAny: minimal finding fixtures
    ] as any,
    aggression: {
      level: "balanced",
      default: "balanced",
      override: null,
      cutoff: 0.5,
      cutoffs: CUTOFFS,
    },
    blocked: true,
    in_scope_open_count: 2,
  };
}

afterEach(() => cleanup());

describe("VerificationStats", () => {
  it("shows total / blocking / warnings / resolved / needs at the active cutoff", () => {
    render(<VerificationStats fileId="LF-1" data={status()} activeLevel="balanced" />);
    // Labels present.
    for (const label of ["Findings", "Blocking", "Warnings", "Resolved", "Needs"]) {
      expect(screen.getByText(label)).toBeDefined();
    }
    // Blocking = 1 open red in-scope; Warnings = 1 open yellow in-scope (the 0.2 one is below
    // the 0.5 cutoff); Resolved = 1; Needs = 2 (mocked); Findings total = 4.
    expect(screen.getByText("4")).toBeDefined(); // total
    expect(screen.getAllByText("1").length).toBeGreaterThanOrEqual(2); // blocking + resolved
    expect(screen.getByText("2")).toBeDefined(); // needs
  });
});
