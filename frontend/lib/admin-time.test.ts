import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { auditTimeLabel, signInLabel } from "./admin-time";

describe("admin times", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-11-13T12:00:00Z"));
  });
  afterEach(() => vi.useRealTimers());

  it("says today in words and older days as dates", () => {
    expect(auditTimeLabel("2026-11-13T09:20:00Z")).toBe("Today 9:20");
    expect(auditTimeLabel("2026-11-09T16:41:00Z")).toBe("Nov 9 16:41");
    expect(signInLabel("2026-11-12T08:00:00Z")).toBe("Yesterday");
    expect(signInLabel(null)).toBe("Never");
  });

  it("adds the year once it is not this one, so two Novembers do not read alike (finding 8)", () => {
    expect(auditTimeLabel("2025-11-09T16:41:00Z")).toBe("Nov 9 2025 16:41");
  });
});
