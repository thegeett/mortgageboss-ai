import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import {
  CONFIDENCE_CRITICAL,
  CONFIDENCE_STANDARD,
  type FieldTier,
  TIER_LABEL,
  tierFor,
  tierInputFor,
} from "./confidence";

const ORDINARY = { confidence: 0.99, critical: false, distrustedReason: null };

describe("the thresholds", () => {
  it("match the stylesheet, which is where the ticket says they live", () => {
    // Two definitions of one number can disagree, and the CSS side is read by
    // nothing, so nothing would notice. This is what stops that.
    const css = readFileSync("app/globals.css", "utf8");
    const read = (name: string) => {
      const match = css.match(new RegExp(`--${name}:\\s*([0-9.]+)`));
      if (!match?.[1]) throw new Error(`--${name} is not defined in globals.css`);
      return Number(match[1]);
    };
    expect(read("confidence-standard")).toBe(CONFIDENCE_STANDARD);
    expect(read("confidence-critical")).toBe(CONFIDENCE_CRITICAL);
  });
});

describe("tierFor", () => {
  it("gives a rated, ordinary, above-threshold field no reason to be looked at", () => {
    expect(tierFor(ORDINARY)).toBe<FieldTier>("confident");
  });

  it("checks an ordinary field below the standard threshold", () => {
    expect(tierFor({ ...ORDINARY, confidence: 0.84 })).toBe<FieldTier>("check");
  });

  it("treats the threshold itself as passing", () => {
    expect(tierFor({ ...ORDINARY, confidence: CONFIDENCE_STANDARD })).toBe<FieldTier>("confident");
  });

  it("does not call an unrated field confident", () => {
    // 544 of 734 stored fields have no confidence key. Rendering them exactly like
    // a rated 0.99 would show the absence of a rating as a positive one.
    expect(tierFor({ ...ORDINARY, confidence: null })).toBe<FieldTier>("unrated");
  });

  describe("criticality overrides confidence", () => {
    it("checks a critical field the model is certain about", () => {
      expect(tierFor({ ...ORDINARY, confidence: 1, critical: true })).toBe<FieldTier>("check");
    });

    it("checks a critical field at exactly the critical threshold", () => {
      // The AC's own example: "a 0.97 loan amount ... still gets flagged".
      const input = { ...ORDINARY, confidence: CONFIDENCE_CRITICAL, critical: true };
      expect(tierFor(input)).toBe<FieldTier>("check");
    });

    it("checks a critical field with no rating at all", () => {
      // A missing rating must not buy a critical field a pass — which is what
      // reading the number before the flag would do.
      expect(tierFor({ ...ORDINARY, confidence: null, critical: true })).toBe<FieldTier>("check");
    });
  });

  describe("a known-bad extractor field", () => {
    it("is checked however sure the model says it is", () => {
      // The whole point of the LP-508 list: the number lied. A hallucinated licence
      // expiry arrives at 0.99.
      const input = { confidence: 1, critical: false, distrustedReason: "doc 146 — hallucinated" };
      expect(tierFor(input)).toBe<FieldTier>("check");
    });
  });

  describe("human confirmation", () => {
    it("outranks everything the model reports", () => {
      const input = { ...ORDINARY, confidence: 0.1, critical: true, humanConfirmed: true };
      expect(tierFor(input)).toBe<FieldTier>("verified");
    });

    it("defaults to false, because no producer sets it today", () => {
      expect(tierFor({ ...ORDINARY, critical: true })).toBe<FieldTier>("check");
    });
  });
});

describe("tierInputFor", () => {
  it("treats a field the backend said nothing about as ordinary", () => {
    expect(tierInputFor(0.9, undefined)).toEqual({
      confidence: 0.9,
      critical: false,
      distrustedReason: null,
      humanConfirmed: false,
      rejected: false,
      removed: false,
    });
  });

  it("carries the backend's flags through", () => {
    const scrutiny = {
      critical: true,
      distrusted_reason: "doc 104",
      sensitive: false,
      verdict: null,
      corrected_value: null,
    };
    expect(tierInputFor(null, scrutiny)).toEqual({
      confidence: null,
      critical: true,
      distrustedReason: "doc 104",
      humanConfirmed: false,
      rejected: false,
      removed: false,
    });
  });

  it("reads an accepted or corrected verdict as human confirmation", () => {
    // The bug this closes: the mark beside a row built its inputs separately from
    // the keyboard queue, so an accepted field dropped out of the loop and went on
    // rendering "Check this".
    const base = {
      critical: true,
      distrusted_reason: null,
      sensitive: false,
      corrected_value: null,
    };
    expect(tierInputFor(0.5, { ...base, verdict: "accepted" }).humanConfirmed).toBe(true);
    expect(tierInputFor(0.5, { ...base, verdict: "corrected" }).humanConfirmed).toBe(true);
  });

  it("does not read a rejection as confirmation", () => {
    const base = {
      critical: true,
      distrusted_reason: null,
      sensitive: false,
      corrected_value: null,
    };
    expect(tierInputFor(0.5, { ...base, verdict: "rejected" }).humanConfirmed).toBe(false);
  });
});

describe("the words", () => {
  it("has one for every tier", () => {
    // DERIVED, not listed. The hand-written list said "verified, confident, check,
    // unrated" and went on passing after `rejected` was added — a test named "every
    // tier" that could only ever check the tiers its author remembered. `TIER_LABEL`
    // is a `Record<FieldTier, string>`, so tsc guarantees its keys ARE every tier.
    const tiers = Object.keys(TIER_LABEL) as FieldTier[];
    expect(tiers).toContain("rejected");
    for (const tier of tiers) expect(TIER_LABEL[tier]).toBeTruthy();
  });
});

describe("a field a person rejected", () => {
  /**
   * `tierInputFor` says a rejection "must keep its mark". It did not.
   *
   * A rejection sets `humanConfirmed: false`, correctly — "I could not verify this"
   * is not "this is right". But false only returns the field to the ordinary path,
   * and on that path a non-critical field rated at or above the standard threshold
   * is `confident`, which renders NOTHING. So a processor could reject a value and
   * watch the row go silent: their own decision, invisible, on the screen built to
   * show decisions.
   */
  const rejected = {
    critical: false,
    distrusted_reason: null,
    sensitive: false,
    corrected_value: null,
    verdict: "rejected",
  } as const;

  it("is not confident, however sure the model was", () => {
    expect(tierFor(tierInputFor(0.99, rejected))).not.toBe("confident");
  });

  it("is not treated as confirmed either", () => {
    expect(tierFor(tierInputFor(0.99, rejected))).not.toBe("verified");
  });

  it("says it was rejected, rather than borrowing the model's word for it", () => {
    // "Check this" is what an unrated or low-confidence field says. A rejection is a
    // person's finding, not the model's hesitation, and the row has to tell them apart.
    expect(tierFor(tierInputFor(0.99, rejected))).toBe("rejected");
    expect(TIER_LABEL.rejected).toBe("Rejected");
  });

  it("still says so when the model gave no rating at all", () => {
    expect(tierFor(tierInputFor(null, rejected))).toBe("rejected");
  });
});

describe("the two verdicts that change what the checks read (LP-703)", () => {
  const BARE = {
    critical: false,
    distrusted_reason: null,
    sensitive: false,
    corrected_value: null,
  };

  it("counts an ADDED field as confirmed by a person", () => {
    // A processor read the document and typed what it says. That is the same act
    // as correcting and a stronger one than accepting. Without this an added
    // field rendered "Not rated" — no sign at all that a human supplied the one
    // value on the row they are answerable for.
    expect(tierFor(tierInputFor(null, { ...BARE, verdict: "added" }))).toBe("verified");
  });

  it("gives a REMOVED field its own tier", () => {
    expect(tierFor(tierInputFor(0.99, { ...BARE, verdict: "removed" }))).toBe("removed");
  });

  it("shows the removal, not an earlier correction, when a field has both in turn", () => {
    // The verdict is one live row, so this is really asserting the ORDER in
    // `tierFor`: `removed` is checked before `humanConfirmed`, or a field
    // corrected and then removed would still read as verified.
    expect(
      tierFor({
        confidence: 0.2,
        critical: true,
        distrustedReason: null,
        humanConfirmed: true,
        removed: true,
      }),
    ).toBe("removed");
  });

  it("a removal outranks a high confidence, a criticality and a distrust reason", () => {
    // Every other signal describes how the value was READ. Once a person says the
    // field is not on the document, none of them is the point any more.
    expect(
      tierFor({
        confidence: 0.99,
        critical: true,
        distrustedReason: "this extractor has read it wrong before",
        removed: true,
      }),
    ).toBe("removed");
  });
});
