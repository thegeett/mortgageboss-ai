import { describe, expect, it } from "vitest";

import { catchAllDisplay, catchAllIsSensitive, extractionFields } from "@/lib/loan-files/documents";

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

describe("a working identifier is read, not hidden", () => {
  /**
   * THE TWO MASKING PATHS DISAGREED ABOUT ONE FIELD (LP-702 review).
   *
   * A typed-core `loan_number` is shown: the backend's `pii_readable` list
   * (`critical_fields.yaml`) records it, with twenty-five others, as
   * classified-PII-but-displayed — kept out of LLM snapshots and analytics views,
   * and put on the processor's own screen, because reading it IS the job.
   *
   * The same loan number inside a nested row was masked to `••••6789`. Row keys
   * are names the model chose, so `field_scrutiny` never reports on them, and the
   * bare 9+ digit rule spoke for it instead. The result depended on the LENDER —
   * an 8-digit loan number rendered, a 10-digit one did not — which is not a
   * distinction about sensitivity at all.
   */
  it.each([
    ["Loan number", "0123456789"],
    ["Policy number", "9876543210"],
    ["Case number", "202600012345"],
    ["Permit number", "0000123456789"],
  ])("shows %s = %s however long the run of digits", (label, value) => {
    expect(catchAllIsSensitive(label, value)).toBe(false);
    expect(catchAllDisplay(label, value)).toBe(value);
  });

  it("still masks an account number of the very same length", () => {
    // The control. If the fix had simply weakened the digit rule, this would pass
    // too — and an account number is the thing that rule exists for.
    expect(catchAllIsSensitive("Account number", "0123456789")).toBe(true);
  });

  it.each([
    ["Claim number", "0000123456789"],
    ["Account number", "0000123456789"],
    ["Routing number", "021000021000"],
    ["Card number", "4147202512345678"],
  ])("still masks %s — it is NOT on the backend's readable list", (label, value) => {
    // THE CONTROL ON THE ALLOW-LIST. `READABLE_IDENTIFIER_LABEL` makes things LESS
    // masked, so an over-wide alternative in it is green by construction and no
    // mutation of the code under test would find it. A first draft included
    // `claim`, and `claim_number_masked` is masked on the backend — the rule meant
    // to stop over-masking would have un-masked a real identifier.
    expect(catchAllIsSensitive(label, value)).toBe(true);
  });

  it("still masks an SSN SHAPE under a readable label", () => {
    // Checked BEFORE the readable-label rule on purpose: a dashed 123-45-6789 is
    // an SSN whoever labelled the column.
    expect(catchAllDisplay("Loan number", "123-45-6789")).toBe("•••-••-6789");
  });
});

describe("every nested cell reaches the mask (LP-702 review)", () => {
  const rowsOf = (data: Record<string, unknown>) => extractionFields(data)[0]?.rows;

  it("masks a list of bare identifier strings", () => {
    // The one path that skipped the identifier test entirely: `tableFrom`'s
    // non-object branch called `leafDisplay` directly, so a list of plain strings
    // rendered in the clear while the same value inside an object row was masked.
    expect(rowsOf({ borrower_identifiers: { value: ["123-45-6789", "987654321"] } })).toEqual([
      ["•••-••-6789"],
      ["•••-••-4321"],
    ]);
  });

  it("does not let a money sibling clear the identifier beside it", () => {
    // `compactRecord` joined the entries and the mask was applied to the LINE, so
    // the money exclusion fired on the balance's cents and cleared the whole cell.
    const rows = rowsOf({
      tradelines: {
        value: [{ creditor: "Chase", account: { number: "123456789", balance: "450.00" } }],
      },
    });
    expect(rows?.[0]?.[1]).toBe("Number: •••-••-6789 · Balance: 450.00");
  });

  it("keeps the provenance sentence and redacts only the identifier in it", () => {
    // A snippet is the quoted line a row was read from — the only provenance a
    // nested row has. Masking the cell replaced it outright, and took the last-4
    // from the BALANCE rather than the card.
    const rows = rowsOf({
      tradelines: {
        value: [{ creditor: "Chase", snippet: "CHASE CARD 4147202512345678 Balance 1,203" }],
      },
    });
    expect(rows?.[0]?.[1]).toBe("CHASE CARD ••••5678 Balance 1,203");
  });
});
