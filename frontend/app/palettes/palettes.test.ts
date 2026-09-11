/**
 * Every palette is complete, and readable, in both themes (LP-901).
 *
 * The colour system is two layers: a PALETTE (app/palettes/*.css, raw colours)
 * and ROLES (app/globals.css, what each colour is for). Swapping a palette is
 * only safe if nothing about a palette has to be remembered, so this file checks
 * what used to be a comment:
 *
 *  - the default palette's light block defines the vocabulary, and every block of
 *    every palette defines exactly it — a palette missing `--amber` would leave
 *    every warning in the app on the default's amber, which looks like a palette
 *    that works;
 *  - every colour role is `var(--palette-colour)`, so no role can quietly hold a
 *    value that ignores the palette;
 *  - the contrast floors, COMPUTED from the values rather than measured once and
 *    written down. globals.css used to say "every text tone clears 4.5:1 …
 *    verified, not assumed"; that sentence was true of one palette and would have
 *    stayed on screen, true-sounding, after the next one arrived.
 */
import { readFileSync, readdirSync } from "node:fs";
import resolveConfig from "tailwindcss/resolveConfig";
import { describe, expect, it } from "vitest";
import config from "../../tailwind.config";

const DIR = new URL("./", import.meta.url);
const read = (path: string) => readFileSync(new URL(path, DIR), "utf8");

/** The palette `:root` and `.dark` apply with no attribute on <html>. */
const DEFAULT_PALETTE = "petrol";

// ---------------------------------------------------------------------------
// Parsing. Palette files are flat — `selector { --x: value; … }`, no nesting —
// and are kept that way, so a small reader is enough and a real CSS parser would
// be one more dependency to answer the same question.
// ---------------------------------------------------------------------------

type Props = Record<string, string>;

function stripComments(css: string): string {
  return css.replace(/\/\*[\s\S]*?\*\//g, "");
}

/** Each top-level rule of a flat stylesheet: its selector and its custom properties. */
function flatRules(css: string): { selector: string; props: Props }[] {
  const out: { selector: string; props: Props }[] = [];
  for (const [, selector, body] of stripComments(css).matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    const props: Props = {};
    for (const [, name, value] of (body as string).matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) {
      props[name as string] = (value as string).trim();
    }
    out.push({ selector: (selector as string).trim(), props });
  }
  return out;
}

/**
 * The `--name: value` declarations directly inside globals.css's `:root` block.
 * globals.css nests its rules inside `@layer base`, so it gets the depth-counting
 * reader tailwind.config.test.ts uses rather than `flatRules`.
 */
function rootRoles(): Props {
  const css = stripComments(read("../globals.css"));
  const start = css.indexOf(":root {");
  if (start === -1) throw new Error("globals.css has no `:root` block");
  let depth = 0;
  let end = start;
  for (let i = css.indexOf("{", start); i < css.length; i++) {
    if (css[i] === "{") depth++;
    else if (css[i] === "}" && --depth === 0) {
      end = i;
      break;
    }
  }
  const out: Props = {};
  for (const [, name, value] of css.slice(start, end).matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) {
    out[name as string] = (value as string).trim();
  }
  return out;
}

// ---------------------------------------------------------------------------
// The palettes on disk, and the selectors each one must use.
// ---------------------------------------------------------------------------

type Mode = "light" | "dark";
const MODES: Mode[] = ["light", "dark"];

/**
 * The two selectors a palette is allowed to use. The default is what <html>
 * gets with no attribute; any other palette is scoped to its `data-palette`,
 * with `:root` in front so it outranks the default's `.dark` whatever order the
 * stylesheets land in (0,2,0 and 0,3,0 against 0,1,0).
 */
function selectorsFor(id: string): Record<Mode, string> {
  return id === DEFAULT_PALETTE
    ? { light: ":root", dark: ".dark" }
    : { light: `:root[data-palette="${id}"]`, dark: `:root[data-palette="${id}"].dark` };
}

const PALETTE_IDS = readdirSync(DIR)
  .filter((name) => name.endsWith(".css"))
  .map((name) => name.replace(/\.css$/, ""))
  .sort();

function palette(id: string): Record<Mode, Props> {
  const rules = flatRules(read(`./${id}.css`));
  const selectors = selectorsFor(id);
  const block = (mode: Mode) => {
    const rule = rules.find((r) => r.selector === selectors[mode]);
    if (!rule) throw new Error(`${id}.css has no \`${selectors[mode]}\` block`);
    return rule.props;
  };
  return { light: block("light"), dark: block("dark") };
}

/** The vocabulary: whatever the default palette's light block defines. */
const COLOUR_NAMES = Object.keys(palette(DEFAULT_PALETTE).light).sort();

/** Every `--x` the resolved Tailwind theme's colours point at — the colour roles. */
const COLOUR_ROLES = (() => {
  const theme = resolveConfig(config).theme;
  const found = new Set<string>();
  for (const [, name] of JSON.stringify(theme?.colors ?? {}).matchAll(/var\((--[\w-]+)\)/g)) {
    found.add(name as string);
  }
  return [...found].sort();
})();

const ROLES = rootRoles();

// ---------------------------------------------------------------------------
// Colour maths. WCAG 2.x relative luminance and contrast ratio.
// ---------------------------------------------------------------------------

type Rgb = [number, number, number];

/** "187.9 67.9% 22%" → sRGB in 0..1. */
function hslToRgb(triple: string): Rgb {
  const [h, s, l] = triple.replace(/%/g, "").split(/\s+/).map(Number) as [number, number, number];
  const sat = s / 100;
  const light = l / 100;
  const a = sat * Math.min(light, 1 - light);
  const channel = (n: number) => {
    const k = (n + h / 30) % 12;
    return light - a * Math.max(-1, Math.min(k - 3, 9 - k, 1));
  };
  return [channel(0), channel(8), channel(4)];
}

function luminance([r, g, b]: Rgb): number {
  const linear = (c: number) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  return 0.2126 * linear(r) + 0.7152 * linear(g) + 0.0722 * linear(b);
}

function contrast(a: Rgb, b: Rgb): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}

/** `bg-x/10` painted over a ground: the colour a tinted chip actually shows. */
function over(fill: Rgb, alpha: number, ground: Rgb): Rgb {
  return fill.map((c, i) => c * alpha + (ground[i] as number) * (1 - alpha)) as Rgb;
}

/** A role's colour in one palette and theme: role → `var(--colour)` → triple. */
function resolver(values: Props) {
  return (role: string): Rgb => {
    const ref = ROLES[`--${role}`]?.match(/^var\((--[\w-]+)\)$/)?.[1];
    if (!ref) throw new Error(`--${role} is not a palette reference in globals.css`);
    const value = values[ref];
    if (!value) throw new Error(`--${role} points at ${ref}, which the palette does not define`);
    return hslToRgb(value);
  };
}

// ---------------------------------------------------------------------------
// The pairs. Each is a claim the UI actually makes, not a grid of every token
// against every other.
// ---------------------------------------------------------------------------

/** Surfaces text sits on: the page, raised and overlaid panels, subtle and hover fills. */
const GROUNDS = ["background", "card", "popover", "muted", "secondary", "accent"];

/** Text written directly on a ground — the three neutral tones and every coloured one. */
const TEXT_ON_GROUND = [
  "foreground",
  "foreground-2",
  "muted-foreground",
  "primary",
  "destructive",
  "success",
  "warning",
  "info",
  "ai",
];

/** Roles used as a FILL, each with its `-foreground` laid on top. */
const FILLS = [
  "primary",
  "secondary",
  "muted",
  "accent",
  "card",
  "popover",
  "destructive",
  "success",
  "warning",
  "info",
  "ai",
];

/**
 * The tinted chip: `bg-x/10 text-x` (status-token.tsx `CHIP`). /10 is the
 * house tint — 62 of the app's 108 status-fill opacities, and the only one the
 * status map uses. The tint lowers the contrast of the very text it frames.
 */
const CHIPS = ["destructive", "success", "warning", "info", "ai"];
const CHIP_TINT = 0.1;
const CHIP_GROUNDS = ["background", "card"];

const TEXT_FLOOR = 4.5; // WCAG 1.4.3, normal text
const NON_TEXT_FLOOR = 3; // WCAG 1.4.11, control borders and the focus ring

type Case = { label: string; ratio: number; floor: number };

function cases(values: Props): Case[] {
  const c = resolver(values);
  const out: Case[] = [];
  for (const text of TEXT_ON_GROUND) {
    for (const ground of GROUNDS) {
      out.push({
        label: `text-${text} on bg-${ground}`,
        ratio: contrast(c(text), c(ground)),
        floor: TEXT_FLOOR,
      });
    }
  }
  for (const fill of FILLS) {
    out.push({
      label: `text-${fill}-foreground on bg-${fill}`,
      ratio: contrast(c(`${fill}-foreground`), c(fill)),
      floor: TEXT_FLOOR,
    });
  }
  for (const chip of CHIPS) {
    for (const ground of CHIP_GROUNDS) {
      out.push({
        label: `text-${chip} on bg-${chip}/10 over bg-${ground}`,
        ratio: contrast(c(chip), over(c(chip), CHIP_TINT, c(ground))),
        floor: TEXT_FLOOR,
      });
    }
  }
  for (const edge of ["input", "ring"]) {
    for (const ground of ["background", "card"]) {
      out.push({
        label: `${edge} on bg-${ground}`,
        ratio: contrast(c(edge), c(ground)),
        floor: NON_TEXT_FLOOR,
      });
    }
  }
  return out;
}

// ---------------------------------------------------------------------------

describe("the palettes on disk", () => {
  it("finds the default palette, so every check below has something to run against", () => {
    // The control: with no palettes found, every `it.each` below is empty and green.
    expect(PALETTE_IDS).toContain(DEFAULT_PALETTE);
    expect(COLOUR_NAMES.length).toBeGreaterThan(0);
  });

  it("every palette is imported by the root layout", () => {
    // A palette file nobody imports is a palette that looks finished and applies
    // nothing — the attribute gets stamped and every role falls through to the
    // default's colours.
    const layout = read("../layout.tsx");
    for (const id of PALETTE_IDS) {
      expect(layout, `app/layout.tsx does not import ./palettes/${id}.css`).toContain(
        `import "./palettes/${id}.css";`,
      );
    }
  });
});

describe.each(PALETTE_IDS)("palette `%s`", (id) => {
  it("has exactly its light and dark blocks", () => {
    // A block under any other selector — a typo in the attribute, a stray
    // `.dark` on a non-default palette — would either never apply or override
    // the default everywhere. Neither fails loudly on screen.
    const selectors = flatRules(read(`./${id}.css`))
      .map((r) => r.selector)
      .sort();
    expect(selectors).toEqual(Object.values(selectorsFor(id)).sort());
  });

  it.each(MODES)("defines exactly the palette vocabulary in %s", (mode) => {
    // Missing: that colour silently comes from the default palette (or, for
    // dark, from light). Extra: a colour no role can reach, which is a palette
    // that looks tuned and isn't.
    expect(Object.keys(palette(id)[mode]).sort()).toEqual(COLOUR_NAMES);
  });

  it.each(MODES)("holds only space-separated HSL triples in %s", (mode) => {
    // The role layer hands these to hsl(var(--x)); a hex value there compiles to
    // an invalid colour and every opacity modifier on it disappears (ADR-389).
    for (const [name, value] of Object.entries(palette(id)[mode])) {
      expect(value, name).toMatch(/^\d+(\.\d+)? \d+(\.\d+)?% \d+(\.\d+)?%$/);
    }
  });

  it.each(MODES)("meets every contrast floor in %s", (mode) => {
    const failing = cases(palette(id)[mode])
      .filter((c) => c.ratio < c.floor)
      .map((c) => `${c.label}: ${c.ratio.toFixed(2)}:1, needs ${c.floor}:1`);
    expect(failing, `${id} (${mode})`).toEqual([]);
  });

  it.each(MODES)("keeps `border` and `input` apart in %s", (mode) => {
    // `border` is the decorative hairline; `input` is the control border held to
    // 3:1. Collapsing them would drop every control border below the floor.
    // Compared by RESOLVED value: two roles naming different palette colours
    // can still be given the same value by a palette.
    const c = resolver(palette(id)[mode]);
    expect(c("border")).not.toEqual(c("input"));
  });
});

describe("the role layer", () => {
  it.each(COLOUR_ROLES)("`%s` names a palette colour", (role) => {
    // A role holding a literal ignores the palette: it stays that colour under
    // every palette and in dark mode, which is wrong rather than missing.
    const ref = ROLES[role]?.match(/^var\((--[\w-]+)\)$/)?.[1];
    expect(ref, `${role} in globals.css should be var(--<palette colour>)`).toBeDefined();
    expect(COLOUR_NAMES).toContain(ref);
  });

  it("the contrast check fails when it should", () => {
    // The control. If `cases` produced nothing, or the maths always said 21:1,
    // "meets every contrast floor" would pass for any palette at all.
    const washedOut = Object.fromEntries(COLOUR_NAMES.map((name) => [name, "0 0% 50%"]));
    expect(cases(washedOut).every((c) => c.ratio < c.floor)).toBe(true);
    expect(contrast(hslToRgb("0 0% 0%"), hslToRgb("0 0% 100%"))).toBeCloseTo(21, 5);
  });
});
