/**
 * The design tokens the codebase already writes must actually resolve.
 *
 * These assertions are deliberately about the RESOLVED Tailwind theme rather than
 * about markup, because that is where both LP-UI bugs actually lived. A component
 * test can only see the class string, and in both cases the class string was
 * correct — `border-danger/40` was on `FailedRunBanner` the whole time, and the
 * config comment claimed 700 did not exist. What was wrong was what the config
 * did with them, which is invisible to JSDOM and visible here.
 */
import resolveConfig from "tailwindcss/resolveConfig";
import { describe, expect, it } from "vitest";
import config from "./tailwind.config";

const theme = resolveConfig(config).theme;

/** `text-red-500` style tokens resolve to a string; `pair()` tokens to an object. */
function colour(name: string): string {
  const value = theme?.colors?.[name as keyof typeof theme.colors];
  if (typeof value === "string") return value;
  if (value && typeof value === "object" && "DEFAULT" in value) {
    return (value as { DEFAULT: string }).DEFAULT;
  }
  throw new Error(`colour token "${name}" does not exist in the resolved theme`);
}

describe("the `danger` colour", () => {
  // LP-UI-002. Twenty class names across four files were written against a colour
  // the config never defined, so `border-danger/40 bg-danger/5 text-danger`
  // compiled to nothing and FailedRunBanner — the banner that reports a dead
  // verification run — rendered grey. Nothing failed; the classes simply vanished.
  it("exists, so the twenty existing call sites resolve", () => {
    expect(() => colour("danger")).not.toThrow();
  });

  it("is the same colour as `destructive`, not a second red", () => {
    expect(colour("danger")).toBe(colour("destructive"));
  });

  it("carries a foreground, so `bg-danger text-danger-foreground` works", () => {
    expect(theme?.colors?.danger).toHaveProperty("foreground");
  });
});

describe("the font-weight cap", () => {
  // LP-UI-001 finding A1. `fontWeight` sat under `theme.extend`, and `extend`
  // MERGES with the default scale rather than replacing it, so `bold: 700`
  // survived and `font-bold` still resolved. Moving the block to `theme` level is
  // what makes SPEC rule 2 real; this test is what stops it drifting back.
  it("does not define 700 — there is no `font-bold` in this system", () => {
    // Read through an index signature deliberately: with the scale replaced,
    // `theme.fontWeight` narrows to exactly {normal, medium, semibold} and
    // `.bold` is a type error rather than a value. That is the cap holding at
    // compile time; this assertion is the same fact at run time, and it is the
    // one that survives if the config is ever loosened back to `any`.
    const weights = theme?.fontWeight as Record<string, string | undefined>;
    expect(weights.bold).toBeUndefined();
  });

  it("defines only 400, 500 and 600", () => {
    expect(theme?.fontWeight).toEqual({
      normal: "400",
      medium: "500",
      semibold: "600",
    });
  });
});

describe("the tokens the redesign adds", () => {
  // These are new in LP-UI-001 and the screen tickets are about to lean on them.
  // A missing one fails the same silent way `danger` did.
  it.each(["foreground-2", "border-strong", "skeleton", "ai", "success", "warning", "info"])(
    "`%s` resolves",
    (name) => {
      expect(() => colour(name)).not.toThrow();
    },
  );

  it("keeps `border` and `input` as two different colours", () => {
    // `border` is the decorative hairline; `input` is the control border held to
    // WCAG 1.4.11's 3:1. Collapsing them back into one value would silently drop
    // every control border below the contrast floor.
    expect(colour("border")).not.toBe(colour("input"));
  });
});
