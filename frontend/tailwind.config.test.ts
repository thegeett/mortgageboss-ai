/**
 * The design tokens the codebase already writes must actually resolve.
 *
 * These assertions are deliberately about the RESOLVED Tailwind theme and about
 * globals.css, rather than about markup, because that is where both LP-UI bugs
 * actually lived. A component test can only see the class string, and in both
 * cases the class string was correct — `border-danger/40` was on
 * `FailedRunBanner` the whole time, and the config comment claimed 700 did not
 * exist. What was wrong was what the config and the stylesheet did with them,
 * which is invisible to JSDOM and visible here.
 */
import { readFileSync } from "node:fs";
import resolveConfig from "tailwindcss/resolveConfig";
import { describe, expect, it } from "vitest";
import config from "./tailwind.config";

const theme = resolveConfig(config).theme;

/**
 * The resolved theme is only half the contract. `colour("input")` is the literal
 * string "hsl(var(--input))" no matter what --input is set to — or whether it is
 * set at all — so an assertion phrased against the resolved theme alone cannot
 * see either failure mode that has actually bitten this codebase: a variable
 * that does not exist (LP-UI-002, `danger`), and two variables silently given
 * the same value. Both live in globals.css, so both are checked against it.
 */
const css = readFileSync(new URL("./app/globals.css", import.meta.url), "utf8");

/** The `--name: value` declarations directly inside one selector's block. */
function customProperties(selector: string): Record<string, string> {
  const start = css.indexOf(`${selector} {`);
  if (start === -1) throw new Error(`globals.css has no \`${selector}\` block`);
  let depth = 0;
  let end = start;
  for (let i = css.indexOf("{", start); i < css.length; i++) {
    if (css[i] === "{") depth++;
    else if (css[i] === "}" && --depth === 0) {
      end = i;
      break;
    }
  }
  const out: Record<string, string> = {};
  for (const [, name, value] of css.slice(start, end).matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) {
    out[name as string] = (value as string).trim();
  }
  return out;
}

const ROOT = customProperties(":root");
const DARK = customProperties(".dark");

/** Every `--x` the resolved theme's colours point at. */
function referencedColourVars(): string[] {
  const found = new Set<string>();
  for (const [, name] of JSON.stringify(theme?.colors ?? {}).matchAll(/var\((--[\w-]+)\)/g)) {
    found.add(name as string);
  }
  return [...found].sort();
}

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

describe("the type scale", () => {
  // Same trap as the weight cap, and it caught this file out once: `fontSize` sat
  // under `theme.extend`, which MERGES, so Tailwind's stock ramp survived above
  // `2xl` — `text-3xl` resolved to 30px with no tracking while xs..2xl had been
  // retuned. Moving it to theme level replaces the scale; this pins the result.
  it("replaces the stock ramp rather than extending it", () => {
    expect(Object.keys(theme?.fontSize ?? {}).sort()).toEqual(
      ["2xl", "3xl", "base", "field", "label", "lg", "sm", "xl", "xs"].sort(),
    );
  });

  it("has no size above 3xl — the scale is the whole vocabulary", () => {
    const sizes = theme?.fontSize as Record<string, unknown>;
    for (const absent of ["4xl", "5xl", "6xl", "7xl", "8xl", "9xl"]) {
      expect(sizes[absent], `\`text-${absent}\` would compile to nothing`).toBeUndefined();
    }
  });

  it("keeps `field` at 16px, the iOS auto-zoom floor", () => {
    // Mobile Safari zooms the viewport whenever a focused control computes under
    // 16px, and does not zoom back out. Every form control wears
    // `text-field md:text-sm`; dropping this below 1rem re-arms that on every
    // field in the app. `text-base md:text-sm`, the usual guard, does NOT work
    // in this scale — `base` is 14px here.
    const field = (theme?.fontSize as Record<string, [string, unknown] | undefined>).field;
    expect(field?.[0]).toBe("1rem");
  });
});

describe("the tokens the redesign adds", () => {
  // These are new in LP-UI-001 and the screen tickets are about to lean on them.
  // A missing one fails the same silent way `danger` did.
  it.each(["foreground-2", "border-strong", "skeleton", "ai", "success", "warning", "info"])(
    "`%s` resolves in the theme",
    (name) => {
      expect(() => colour(name)).not.toThrow();
    },
  );

  // ...and the half the theme cannot see: the variable behind the token. Deleting
  // `--ai` from globals.css leaves the assertion above green while every
  // `bg-ai/10` in the tree compiles to nothing — exactly the LP-UI-002 failure.
  it.each(referencedColourVars())("`%s` is defined in :root", (name) => {
    expect(ROOT[name]).toBeDefined();
  });

  it.each(referencedColourVars())("`%s` is defined in .dark", (name) => {
    // Colour tokens must be re-stated for the dark theme; one left out inherits
    // the light value and is wrong rather than missing, which is harder to spot.
    expect(DARK[name]).toBeDefined();
  });

  it("keeps `border` and `input` as two different colours", () => {
    // `border` is the decorative hairline; `input` is the control border held to
    // WCAG 1.4.11's 3:1. Collapsing them back into one value would silently drop
    // every control border below the contrast floor. Compared by VALUE: the
    // resolved theme gives back two different `hsl(var(--x))` strings whatever
    // the variables say, so comparing those can never fail.
    expect(ROOT["--border"]).not.toBe(ROOT["--input"]);
    expect(DARK["--border"]).not.toBe(DARK["--input"]);
  });
});
