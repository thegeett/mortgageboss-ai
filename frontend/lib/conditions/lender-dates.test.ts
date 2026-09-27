import type { ConditionRound } from "@/lib/types/conditions";
import { describe, expect, it } from "vitest";
import {
  daysUntil,
  expiryLine,
  lenderDates,
  lenderFactsFor,
  roundWithLenderDates,
  soonestExpiry,
} from "./lender-dates";

/**
 * The lender's dates, as arithmetic rather than as a clock (LP-917-lite, S2-11).
 *
 * `today` IS ALWAYS PASSED IN, WHICH IS THE POINT OF TESTING THIS AT ALL. The rail draws a countdown,
 * so a test reading the real clock would pass on the day it was written and fail the next morning. The
 * design's own "· 38 days" is only true for the day the PNG was drawn — asserted below from both sides
 * so the dependency is recorded rather than discovered.
 *
 * THE LABEL LIST IS THE TEST'S OWN, deliberately. These functions take the lender's twelve keys as a
 * parameter precisely so this module holds no second copy of that vocabulary
 * (`review-side-panel.tsx` owns it). Passing a realistic subset here tests the contract; that the RAIL
 * passes the real `EXPIRY` is a type-level fact, not a behavioural one.
 */
const EXPIRY_LABELS = [
  ["close_by", "Close by"],
  ["appraisal", "Appraisal"],
  ["asset", "Asset"],
  ["credit", "Credit"],
  ["income", "Income"],
] as const;

function round(over: Partial<ConditionRound> = {}): ConditionRound {
  return {
    id: `r-${over.round_number ?? 1}`,
    round_number: 1,
    status: "imported",
    completeness: "full",
    sheet_format: "uwm",
    sources: [],
    date_printed: "2026-08-28",
    round_date: "2026-08-28",
    expiry_dates: null,
    draft_rows: null,
    parse_report: {},
    header: null,
    comparison: null,
    condition_count: 0,
    created: null,
    seen_again: null,
    created_at: "2026-08-28T12:00:00Z",
    updated_at: "2026-08-28T12:00:00Z",
    ...over,
  } as ConditionRound;
}

const ROUND_1 = round({
  round_number: 1,
  date_printed: "2026-08-28",
  header: { loan_facts: { "Rate Lock Exp": "", "Must Not Close Before": "09/30/2026" } },
  expiry_dates: { close_by: "2026-10-30", asset: "2026-10-30" },
});

const ROUND_2 = round({
  round_number: 2,
  date_printed: "2026-09-10",
  header: {
    loan_facts: {
      "Must Not Close Before": "09/30/2026",
      "Rate Lock Exp": "09/30/2026",
    },
  },
  expiry_dates: { close_by: "2026-11-03", income: "2026-11-03", asset: "2026-11-30" },
});

describe("roundWithLenderDates", () => {
  it("takes the newest imported round that carries dates, not the newest round", () => {
    // A draft round 3 exists and must not win: it has never been imported.
    const draft = round({ round_number: null, status: "draft", header: { loan_facts: {} } });
    expect(roundWithLenderDates([draft, ROUND_2, ROUND_1])?.round_number).toBe(2);
  });

  it("picks by round number, not by when the row was created", () => {
    // THE DONE-WHEN IS "all taken from round 2 and not round 1". A round imported out of creation
    // order would win on a timestamp, which is why the reducer compares numbers.
    const late1 = round({
      ...ROUND_1,
      created_at: "2026-12-01T00:00:00Z",
    } as Partial<ConditionRound>);
    expect(roundWithLenderDates([late1, ROUND_2])?.round_number).toBe(2);
  });

  it("skips a round with no letter and no expiry table — a paste", () => {
    const paste = round({ round_number: 2, header: null, expiry_dates: null });
    expect(roundWithLenderDates([paste, ROUND_1])?.round_number).toBe(1);
  });

  it("accepts a round with an expiry table but no letterhead", () => {
    // S1-11's case: the reader could not find the header, but the expiry column survives it.
    const headerless = round({
      round_number: 3,
      header: null,
      expiry_dates: { credit: "2026-10-01" },
    });
    expect(roundWithLenderDates([headerless, ROUND_2])?.round_number).toBe(3);
  });

  it("is null when nothing on the file carries a date", () => {
    expect(roundWithLenderDates([round({ header: null, expiry_dates: {} })])).toBeNull();
    expect(roundWithLenderDates([])).toBeNull();
  });

  it("ignores an expiry table whose every value is empty", () => {
    const blank = round({ round_number: 4, header: null, expiry_dates: { close_by: null } });
    expect(roundWithLenderDates([blank])).toBeNull();
  });
});

describe("daysUntil", () => {
  it("counts calendar days, and S2-11's 38 is true only on the day it was drawn", () => {
    // The PNG was drawn with today = 09/26/2026 against a close-by of 11/03/2026.
    expect(daysUntil("2026-11-03", "2026-09-26")).toBe(38);
    // One day later the same fixture is 37. The screen's number is a countdown, not a constant.
    expect(daysUntil("2026-11-03", "2026-09-27")).toBe(37);
  });

  it("is 0 on the day itself and negative once it has passed", () => {
    expect(daysUntil("2026-09-27", "2026-09-27")).toBe(0);
    expect(daysUntil("2026-09-20", "2026-09-27")).toBe(-7);
  });

  it("crosses a month and a year boundary without drifting", () => {
    expect(daysUntil("2026-10-01", "2026-09-30")).toBe(1);
    expect(daysUntil("2027-01-01", "2026-12-31")).toBe(1);
    // 2028 is a leap year: 29 February exists and the count must include it.
    expect(daysUntil("2028-03-01", "2028-02-28")).toBe(2);
  });

  it("returns null for something that is not a date rather than a number", () => {
    expect(daysUntil("not-a-date", "2026-09-27")).toBeNull();
    expect(daysUntil("2026-11-03", "")).toBeNull();
  });
});

describe("soonestExpiry", () => {
  it("names every row falling on the soonest date, in the lender's table order", () => {
    const expiry = soonestExpiry(ROUND_2, EXPIRY_LABELS, "2026-09-26");
    expect(expiry).not.toBeNull();
    expect(expiry?.date).toBe("2026-11-03");
    // A TIE IS THE ORDINARY CASE and S2-11 names both halves of it.
    expect(expiry?.labels).toEqual(["Close by", "Income"]);
    expect(expiry?.days).toBe(38);
  });

  it("does not pick the later asset date", () => {
    // 11/30 is on the same table and must lose to 11/03.
    expect(soonestExpiry(ROUND_2, EXPIRY_LABELS, "2026-09-26")?.date).not.toBe("2026-11-30");
  });

  it("keeps a date that has already passed, because a lapsed document is the urgent one", () => {
    const lapsed = round({ expiry_dates: { credit: "2026-09-01", close_by: "2026-12-01" } });
    const expiry = soonestExpiry(lapsed, EXPIRY_LABELS, "2026-09-27");
    expect(expiry?.date).toBe("2026-09-01");
    expect(expiry?.days).toBe(-26);
  });

  it("is null when the table is absent or entirely empty", () => {
    expect(soonestExpiry(round({ expiry_dates: null }), EXPIRY_LABELS, "2026-09-27")).toBeNull();
    expect(
      soonestExpiry(round({ expiry_dates: { close_by: null } }), EXPIRY_LABELS, "2026-09-27"),
    ).toBeNull();
  });

  it("ignores a key the caller did not name", () => {
    // `vob` is a real lender key; a caller passing a subset must not have it counted anyway.
    const other = round({ expiry_dates: { vob: "2026-09-28", close_by: "2026-11-03" } });
    expect(soonestExpiry(other, EXPIRY_LABELS, "2026-09-27")?.date).toBe("2026-11-03");
  });
});

describe("lenderDates", () => {
  it("reads the three printed dates and the soonest expiry off round 2", () => {
    const dates = lenderDates([ROUND_1, ROUND_2], EXPIRY_LABELS, "2026-09-26");
    expect(dates).not.toBeNull();
    expect(dates?.roundNumber).toBe(2);
    expect(dates?.datePrinted).toBe("2026-09-10");
    // The Done-when, as data: rate lock and must-not-close-before both 09/30/2026, from round 2.
    expect(dates?.rateLockExpires).toBe("09/30/2026");
    expect(dates?.mustNotCloseBefore).toBe("09/30/2026");
    // S2-11 draws "Must fund by —": this sheet does not print one, and it is not guessed.
    expect(dates?.mustFundBy).toBeNull();
    expect(dates?.soonestExpiry?.date).toBe("2026-11-03");
  });

  it("is null for a file whose only round is a paste", () => {
    // The spec's "No dates from the lender yet." case, which the caller words.
    const paste = round({ round_number: 1, header: null, expiry_dates: null });
    expect(lenderDates([paste], EXPIRY_LABELS, "2026-09-27")).toBeNull();
  });

  it("does not fall back to round 1 for a value round 2 left empty", () => {
    // ROUND_1 prints no rate lock; ROUND_2 does. Reading a field from a DIFFERENT round than the one
    // named in "From round 2, printed 09/10" would attribute round 1's letter to round 2.
    const dates = lenderDates([ROUND_1, ROUND_2], EXPIRY_LABELS, "2026-09-26");
    expect(dates?.soonestExpiry?.date).toBe("2026-11-03");
    expect(dates?.soonestExpiry?.labels).not.toContain("Asset");
  });
});

describe("lenderFactsFor", () => {
  it("reads one round's three dates without re-declaring the lender's labels", () => {
    expect(lenderFactsFor(ROUND_2)).toEqual({
      mustNotCloseBefore: "09/30/2026",
      mustFundBy: null,
      rateLockExpires: "09/30/2026",
    });
  });

  it("treats an empty printed value as absent", () => {
    // ROUND_1 carries `"Rate Lock Exp": ""` — the lender printed the row and left it blank.
    expect(lenderFactsFor(ROUND_1).rateLockExpires).toBeNull();
  });

  it("is all nulls for a round with no letter", () => {
    expect(lenderFactsFor(round({ header: null }))).toEqual({
      mustNotCloseBefore: null,
      mustFundBy: null,
      rateLockExpires: null,
    });
  });
});

describe("expiryLine", () => {
  it("is S2-11's line for the drawn fixture", () => {
    expect(expiryLine({ date: "2026-11-03", labels: ["Close by", "Income"], days: 38 })).toBe(
      "Close by and income docs · 38 days",
    );
  });

  it("lower-cases every name after the first, so it reads as a phrase", () => {
    expect(expiryLine({ date: "x", labels: ["Close by", "Income", "Asset"], days: 5 })).toBe(
      "Close by, income and asset docs · 5 days",
    );
  });

  it("agrees the noun with the number", () => {
    expect(expiryLine({ date: "x", labels: ["Credit"], days: 1 })).toBe("Credit docs · 1 day");
    expect(expiryLine({ date: "x", labels: ["Credit"], days: 0 })).toBe("Credit docs · 0 days");
  });

  it("says a passed date in words rather than with a minus sign", () => {
    expect(expiryLine({ date: "x", labels: ["Credit"], days: -1 })).toBe("Credit docs · 1 day ago");
    expect(expiryLine({ date: "x", labels: ["Credit"], days: -26 })).toBe(
      "Credit docs · 26 days ago",
    );
  });
});
