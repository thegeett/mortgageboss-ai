import { describe, expect, it } from "vitest";
import { formatDuration, lastRunLabel, runDurationSeconds } from "./rule-findings";

/** A stand-in for date-fns, so these assert the LABEL and not the clock. */
const rel = (iso: string) => `on ${iso.slice(0, 10)}`;

const run = (over: Partial<Parameters<typeof lastRunLabel>[0] & object> = {}) =>
  ({
    status: "completed" as const,
    started_at: "2026-09-04T00:08:47Z",
    completed_at: "2026-09-04T00:23:25Z",
    ...over,
  }) as NonNullable<Parameters<typeof lastRunLabel>[0]>;

describe("lastRunLabel", () => {
  it("says when it ran and what it cost", () => {
    // The duration is the half a processor has no other way to find. A pass takes anywhere from one
    // minute to fifteen depending on the file, and pressing Run without knowing which is what made
    // the button feel like a gamble.
    expect(lastRunLabel(run(), rel)).toBe("Last run on 2026-09-04 · took 14m 38s");
  });

  it("renders nothing while a pass is in flight", () => {
    // `latest_run` IS the running pass, so a "last run" line here would describe the run being
    // watched — and its phase and estimate are already on screen two lines up.
    expect(lastRunLabel(run({ status: "running", completed_at: null }), rel)).toBeNull();
    expect(lastRunLabel(null, rel)).toBeNull();
  });

  it("names a failure rather than reporting it as an ordinary run", () => {
    expect(lastRunLabel(run({ status: "failed" }), rel)).toBe(
      "Last run failed on 2026-09-04 · took 14m 38s",
    );
  });

  it("still says when, if it cannot say how long", () => {
    // A run with no `started_at` is older than that field. Degrade to the half that is knowable
    // rather than dropping the line.
    expect(lastRunLabel(run({ started_at: null }), rel)).toBe("Last run on 2026-09-04");
  });
});

describe("runDurationSeconds", () => {
  it("refuses a negative duration rather than rendering one", () => {
    // The two timestamps are written by different statements; clock skew between them would
    // otherwise put "took -3s" on screen, which reads as a bug in the product rather than in a clock.
    expect(
      runDurationSeconds({
        started_at: "2026-09-04T00:23:25Z",
        completed_at: "2026-09-04T00:08:47Z",
      }),
    ).toBeNull();
    expect(
      runDurationSeconds({ started_at: "not a date", completed_at: "2026-09-04T00:08:47Z" }),
    ).toBeNull();
  });
});

describe("formatDuration", () => {
  it("stays compact across the range a run actually spans", () => {
    expect(formatDuration(47)).toBe("47s");
    expect(formatDuration(878)).toBe("14m 38s"); // LF-AYK4's 2026-09-04 run
    expect(formatDuration(900)).toBe("15m");
    expect(formatDuration(3661)).toBe("1h 1m");
  });

  it("does not round a measurement to the minute, unlike the estimate beside it", () => {
    // `remainingLabel` rounds deliberately: it renders an ESTIMATE with real spread. This renders a
    // finished run, where the duration is exactly known — rounding would discard information the
    // processor is reading the line to get.
    expect(formatDuration(878)).not.toBe("15m");
  });
});
