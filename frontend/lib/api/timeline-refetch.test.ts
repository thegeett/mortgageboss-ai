import type { Timeline, TimelineEntry } from "@/lib/types/timeline";
import { afterEach, describe, expect, it, vi } from "vitest";
import { sendInFlightInterval } from "./timeline";

const SENT_AT = "2026-10-31T12:00:00Z";

function timeline(...entries: Partial<TimelineEntry>[]): Timeline {
  return {
    entries: entries.map((entry) => ({ detail: {}, status: null, ...entry }) as TimelineEntry),
    truncated: false,
    inbox_address: null,
    unread_count: 0,
  };
}

afterEach(() => {
  vi.useRealTimers();
});

describe("sendInFlightInterval (LP-997)", () => {
  it("re-checks every 30 seconds while a Send is queued, for 1.5 minutes", () => {
    vi.useFakeTimers();
    const row = { status: "queued", detail: { send_requested_at: SENT_AT } };
    vi.setSystemTime(new Date(Date.parse(SENT_AT) + 5_000));
    expect(sendInFlightInterval(timeline(row))).toBe(30_000);
    vi.setSystemTime(new Date(Date.parse(SENT_AT) + 90_000));
    expect(sendInFlightInterval(timeline(row))).toBe(false);
  });

  it("does not poll for an automatic reply that sits queued", () => {
    expect(sendInFlightInterval(timeline({ status: "queued", detail: {} }))).toBe(false);
    expect(sendInFlightInterval(undefined)).toBe(false);
  });
});
