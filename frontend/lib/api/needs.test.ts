import { MAX_NEEDS_POLLS, NEEDS_POLL_INTERVAL_MS, needsRefetchInterval } from "@/lib/api/needs";
import { describe, expect, it } from "vitest";

describe("needsRefetchInterval — live polling with a backstop", () => {
  it("does not poll when nothing is in flight", () => {
    expect(needsRefetchInterval(false, 0)).toBe(false);
  });

  it("polls while documents are in flight", () => {
    expect(needsRefetchInterval(true, 0)).toBe(NEEDS_POLL_INTERVAL_MS);
    expect(needsRefetchInterval(true, 5)).toBe(NEEDS_POLL_INTERVAL_MS);
  });

  it("stops polling once the backstop is hit (a stuck pipeline)", () => {
    expect(needsRefetchInterval(true, MAX_NEEDS_POLLS + 1)).toBe(false);
  });
});
