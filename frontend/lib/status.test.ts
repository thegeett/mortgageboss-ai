/**
 * The status vocabulary's two load-bearing promises (LP-UI-005):
 * a status reads with the colour removed, and an enum the backend grew shows up
 * instead of crashing the row.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import {
  CALCULATOR_STATUS,
  DOCUMENT_STATUS,
  EVALUATION_OUTCOME,
  LOAN_FILE_STATUS,
  NEEDS_PRIORITY,
  NEEDS_STATUS,
  type StatusMeta,
  type Tone,
  resolveStatus,
} from "@/lib/status";
import type { EvaluationOutcome } from "@/lib/types/verification";
import { describe, expect, it } from "vitest";

const MAPS: Record<string, Record<string, StatusMeta>> = {
  LOAN_FILE_STATUS,
  DOCUMENT_STATUS,
  NEEDS_STATUS,
  NEEDS_PRIORITY,
  EVALUATION_OUTCOME,
  CALCULATOR_STATUS,
};

const TONES: Tone[] = ["blocking", "attention", "verified", "progress", "neutral", "ai"];

describe("every status carries all three channels", () => {
  it.each(Object.entries(MAPS))("%s", (_name, map) => {
    for (const [key, meta] of Object.entries(map)) {
      // WORD — the channel that survives greyscale, monochrome print and a
      // colour vision deficiency. An empty label would leave colour alone.
      expect(meta.label.trim(), `${key} has no label`).not.toBe("");
      // COLOUR + GLYPH are both keyed off the tone, so a valid tone is what
      // guarantees the row gets a glyph at all.
      expect(TONES, `${key} has tone "${meta.tone}"`).toContain(meta.tone);
    }
  });
});

describe("colour is never the only channel", () => {
  // StatusToken maps tone -> glyph and tone -> colour. If two tones shared a
  // glyph, those two would be distinguishable by colour alone, which is exactly
  // what SPEC rule 4 forbids. Read from the component so the test tracks it.
  const source = readFileSync(join(process.cwd(), "components/status-token.tsx"), "utf8");
  const glyphBlock = source.slice(
    source.indexOf("const GLYPH"),
    source.indexOf("};", source.indexOf("const GLYPH")),
  );
  const glyphs = [...glyphBlock.matchAll(/^\s{2}(\w+):\s*(\w+),/gm)].map(([, tone, icon]) => ({
    tone,
    icon,
  }));

  it("assigns a glyph to all six tones", () => {
    expect(glyphs.map((g) => g.tone).sort()).toEqual([...TONES].sort());
  });

  it("gives every tone a DIFFERENT glyph shape", () => {
    const icons = glyphs.map((g) => g.icon);
    expect(new Set(icons).size, `duplicate glyph among ${icons.join(", ")}`).toBe(icons.length);
  });

  it("distinguishes the two tones a processor must never confuse", () => {
    // blocking vs attention is the pair that decides whether a file can move.
    const blocking = glyphs.find((g) => g.tone === "blocking")?.icon;
    const attention = glyphs.find((g) => g.tone === "attention")?.icon;
    expect(blocking).toBeDefined();
    expect(blocking).not.toBe(attention);
  });
});

describe("resolveStatus never returns undefined", () => {
  it("surfaces an enum value the backend grew, humanised", () => {
    const meta = resolveStatus(EVALUATION_OUTCOME, "awaiting_investor_response");
    expect(meta.label).toBe("Awaiting investor response");
    // Routed to `attention`, not `neutral`: an outcome this build does not
    // understand is work someone has to look at, never something to hide.
    expect(meta.tone).toBe("attention");
  });

  it("renders an absent status as an em dash rather than blank", () => {
    for (const value of [null, undefined, ""]) {
      const meta = resolveStatus(LOAN_FILE_STATUS, value);
      expect(meta.label).toBe("—");
      expect(meta.tone).toBe("neutral");
    }
  });

  it("does not throw on any unknown key", () => {
    for (const map of Object.values(MAPS)) {
      expect(() => resolveStatus(map, "definitely_not_a_status")).not.toThrow();
    }
  });

  it("takes a fallback tone, for surfaces where amber would be a false alarm", () => {
    // `attention` is right for a row in a work queue and wrong for a headline
    // figure: a calculator status this build does not recognise is not evidence
    // that the DTI is bad. CalculatorCard passes `neutral` for that reason.
    const meta = resolveStatus(CALCULATOR_STATUS, "capped_by_investor", "neutral");
    expect(meta.tone).toBe("neutral");
    expect(meta.label).toBe("Capped by investor");
  });
});

describe("the wording LP-583 and LP-581 argued out is unchanged", () => {
  // These are the words processors quote in escalations. LP-UI-005 unified the
  // COLOUR vocabulary and nothing else; this test is what keeps that true.
  it.each<[EvaluationOutcome, string]>([
    ["open", "Must fix"],
    ["couldnt_check", "Couldn't check"],
    ["needs_review", "Needs review"],
    ["pending_automation", "Manual review"],
    ["satisfied", "Satisfied"],
    ["no_longer_applies", "No longer applies"],
    ["not_applicable", "Not applicable"],
  ])("%s reads %s", (key, label) => {
    expect(EVALUATION_OUTCOME[key].label).toBe(label);
  });

  it("keeps `completed` as the processing pipeline's word, not a verification claim", () => {
    // `completed` means extraction finished. This product tracks stated vs
    // verified data as a first-class distinction, and NEEDS_STATUS.verified uses
    // "Verified" for the case where something actually was verified.
    expect(DOCUMENT_STATUS.completed.label).toBe("Completed");
    expect(NEEDS_STATUS.verified.label).toBe("Verified");
  });
});
