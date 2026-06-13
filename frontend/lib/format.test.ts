import { formatMoney, humanize } from "@/lib/format";
import { describe, expect, it } from "vitest";

describe("formatMoney", () => {
  it("formats a decimal string as whole-dollar currency", () => {
    expect(formatMoney("360000.00")).toBe("$360,000");
  });

  it("returns a dash for null", () => {
    expect(formatMoney(null)).toBe("—");
  });

  it("returns the input if it isn't a number", () => {
    expect(formatMoney("n/a")).toBe("n/a");
  });
});

describe("humanize", () => {
  it("turns an underscored value into a spaced, title-cased label", () => {
    expect(humanize("primary_residence")).toBe("Primary residence");
    expect(humanize("single_family")).toBe("Single family");
  });

  it("returns a dash for null", () => {
    expect(humanize(null)).toBe("—");
  });
});
