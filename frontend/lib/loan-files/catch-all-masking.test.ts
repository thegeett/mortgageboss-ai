import { describe, expect, it } from "vitest";

import { catchAllDisplay, catchAllIsSensitive } from "@/lib/loan-files/documents";

/**
 * Masking the catch-all (LP-UI-032 review).
 *
 * THE CASES ARE REAL. Every label below is one that appears with a value in the
 * current extraction corpus — including the pair that makes this hard: a nine-digit
 * tax id and a dollar amount, both labelled "social security".
 */
describe("catchAllIsSensitive", () => {
  it("masks a bare nine-digit identifier whatever its label says", () => {
    // The live exposure: W-2 box b, rendered in the clear before this change.
    expect(catchAllIsSensitive("b Employer's social security number", "123456789")).toBe(true);
    expect(catchAllDisplay("b Employer's social security number", "123456789")).toBe("•••-••-6789");
  });

  it("masks an SSN-shaped value", () => {
    expect(catchAllDisplay("Any label at all", "123-45-6789")).toBe("•••-••-6789");
  });

  it("masks a short account number the label identifies", () => {
    expect(catchAllIsSensitive("Brokerage account number", "12345678")).toBe(true);
    expect(catchAllDisplay("Savings Account Number", "4321")).toBe("••••4321");
  });

  it("does NOT mask a withholding amount whose label says social security", () => {
    // The whole reason the value is consulted. These are pay-stub figures; masking
    // them would be a worse bug than the one this fixes.
    for (const [label, value] of [
      ["Social Security - YTD", "$4,200.00"],
      ["OASDI (Social Security) - Current", "161.20"],
      ["Social Security Employer - YTD", "1,240.50"],
      // The case the exclusion EXISTS for, and the one the first version of this
      // test missed: nine contiguous digits, but with cents. The backend's readonly
      // scrub carries the same case ("large amount with cents") for the same reason.
      ["Total Account Number of Shares", "123456789.01"],
    ]) {
      expect(catchAllIsSensitive(label as string, value as string), label).toBe(false);
      expect(catchAllDisplay(label as string, value as string)).toBe(value);
    }
  });

  it("does not mask a status word, a date, or a rate", () => {
    expect(catchAllIsSensitive("SSN Check", "Match")).toBe(false);
    expect(catchAllIsSensitive("Statement Date", "2025-04-04")).toBe(false);
    expect(catchAllIsSensitive("Interest Rate", "6.125")).toBe(false);
    expect(catchAllIsSensitive("Payment", "6028.02")).toBe(false);
  });

  it("leaves an ordinary labelled number alone", () => {
    expect(catchAllDisplay("Pay Period Hours", "86.67")).toBe("86.67");
    expect(catchAllDisplay("Number of Units", "4")).toBe("4");
  });
});
