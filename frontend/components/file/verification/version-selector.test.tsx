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
    //
    // LP-594 — asserted through the ACCESSIBLE NAME, not a `title` attribute. The counts are Radix
    // tooltip triggers now, and the tooltip text only enters the DOM on hover; the name is what a
    // screen reader reads and what survives the trigger being closed, so it is the honest assertion.
    openHistory([run()]);

    expect(screen.getByRole("button", { name: "26 Needs attention" })).toBeDefined();
    expect(screen.getByRole("button", { name: "34 Satisfied" })).toBeDefined();
    expect(screen.getByRole("button", { name: "3 Cross-checks" })).toBeDefined();
  });

  it("gives each number a cursor that says it explains itself", () => {
    // The point of LP-594. A number a processor cannot tell is hoverable is a number they never
    // hover: `title` gave no affordance at all, so the meaning was there and unreachable.
    openHistory([run()]);

    expect(screen.getByRole("button", { name: "26 Needs attention" }).className).toContain(
      "cursor-help",
    );
  });

  it("hides a zero rather than printing it", () => {
    openHistory([run({ cross_check_count: 0 })]);

    expect(screen.queryByRole("button", { name: /Cross-checks/ })).toBeNull();
    expect(screen.getByRole("button", { name: /Needs attention/ })).toBeDefined();
  });

  it("marks a run that produced nothing at all, rather than rendering an empty row", () => {
    openHistory([run({ attention_count: 0, satisfied_count: 0, cross_check_count: 0 })]);

    expect(screen.getByRole("button", { name: /produced no findings/i })).toBeDefined();
  });

  it("closes when the processor clicks away from it", () => {
    // Only matters because it OVERLAYS now. In flow, leaving it open cost a processor nothing; over
    // their findings, a panel with no way out but the trigger reads as stuck.
    openHistory([run()]);
    expect(screen.getByText(/manual/)).toBeDefined();

    fireEvent.pointerDown(document.body);

    expect(screen.queryByText(/manual/)).toBeNull();
  });

  it("closes on Escape", () => {
    openHistory([run()]);

    fireEvent.keyDown(document, { key: "Escape" });

    expect(screen.queryByText(/manual/)).toBeNull();
  });

  it("stays open when the click lands inside it", () => {
    // The dismissal must not fire on the panel's own rows — picking a run is the reason it is open.
    openHistory([run()]);

    fireEvent.pointerDown(screen.getByText(/manual/));

    expect(screen.getByText(/manual/)).toBeDefined();
  });

  it("floats the history over the page instead of pushing everything below it down", () => {
    // Opening the history used to reflow the whole panel — with twenty runs it displaced the
    // findings a processor was reading. Asserted on the panel that WRAPS the list, so the test
    // fails if the positioning is dropped rather than merely moved.
    openHistory([run()]);

    const panel = screen
      .getByText(/purchase|refinance|manual|scheduled|automatic/i)
      .closest("div.absolute");
    expect(panel).not.toBeNull();
    expect(panel?.className).toContain("z-20");
  });
});
