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
import { join } from "node:path";
import { DEFAULT_PALETTE, PALETTES } from "@/lib/theme";
import resolveConfig from "tailwindcss/resolveConfig";
import { describe, expect, it } from "vitest";
import config from "../../tailwind.config";

const DIR = new URL("./", import.meta.url);
const read = (path: string) => readFileSync(new URL(path, DIR), "utf8");

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
 * Text on a TRANSLUCENT fill. What shows is the fill blended into the ground under
 * it, so the text loses contrast that the solid pair never shows:
 *
 *  - the chip, `bg-x/10 text-x` (status-token.tsx `CHIP`). /10 is the heaviest
 *    resting tint a status hue takes — 44 fills at /10, 21 at /5, which is lighter
 *    and so reads better — and the only one the status map uses;
 *  - the drop zone, `bg-primary/15 text-primary` (mismo-upload, document-dropzone);
 *  - hover, `hover:bg-primary/90` and `hover:bg-destructive/90` (Button) and
 *    `hover:bg-primary/80` (Badge's default variant).
 *
 * Badge's `destructive` variant also hovers at /80: 4.09:1 over a card in Petrol
 * light, 4.42:1 in Blue. It has no caller, so it is not listed; its first caller
 * should fix it rather than add it here.
 */
const TINTED: { text: string; fill: string; alpha: number }[] = [
  ...["destructive", "success", "warning", "info", "ai"].map((x) => ({
    text: x,
    fill: x,
    alpha: 0.1,
  })),
  { text: "primary", fill: "primary", alpha: 0.15 },
  { text: "primary-foreground", fill: "primary", alpha: 0.9 },
  { text: "destructive-foreground", fill: "destructive", alpha: 0.9 },
  { text: "primary-foreground", fill: "primary", alpha: 0.8 },
];
const TINT_GROUNDS = ["background", "card"];

/**
 * Faded text that a person measured and exempted: `MEASURED_SAFE` in
 * lib/a11y-contrast.test.ts, e.g. `"text-primary/80": "5.10:1 on bg-card …"`.
 * Each number there was measured on one palette in one theme. With a second
 * palette it is a claim about colours the page may not be showing — Blue light
 * puts `text-primary/80` on a card at 4.59:1, not 5.10 — so every exemption is
 * recomputed here for every palette and theme (LP-902 review). Read from the
 * exemption list itself, so a new exemption is covered without anyone
 * remembering to add it.
 */
const FADED = [
  ...readFileSync(new URL("../../lib/a11y-contrast.test.ts", import.meta.url), "utf8").matchAll(
    /"text-([\w-]+)\/(\d+)":\s*"[\d.]+:1 on bg-([\w-]+)/g,
  ),
].map(([, text, alpha, ground]) => ({
  text: text as string,
  alpha: Number(alpha) / 100,
  ground: ground as string,
}));

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
  for (const { text, fill, alpha } of TINTED) {
    for (const ground of TINT_GROUNDS) {
      out.push({
        label: `text-${text} on bg-${fill}/${Math.round(alpha * 100)} over bg-${ground}`,
        ratio: contrast(c(text), over(c(fill), alpha, c(ground))),
        floor: TEXT_FLOOR,
      });
    }
  }
  for (const { text, alpha, ground } of FADED) {
    out.push({
      label: `text-${text}/${Math.round(alpha * 100)} on bg-${ground} (a11y-contrast exemption)`,
      ratio: contrast(over(c(text), alpha, c(ground)), c(ground)),
      floor: TEXT_FLOOR,
    });
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

  it("reads the measured exemptions it recomputes", () => {
    // The control. A regex that stopped matching MEASURED_SAFE's shape would drop
    // every exemption from the contrast check and leave it green.
    expect(FADED).toContainEqual({ text: "primary", alpha: 0.8, ground: "card" });
    expect(FADED).toContainEqual({ text: "background", alpha: 0.75, ground: "foreground" });
  });

  it("the switcher offers exactly the palettes on disk", () => {
    // LP-902. One way round, the menu offers a palette with no colours and the
    // screen stays on the default; the other, a finished palette nobody can pick.
    expect(PALETTES.map((p) => p.id).sort()).toEqual(PALETTE_IDS);
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

// ---------------------------------------------------------------------------
// The other direction: nothing reaches past the roles into the palette.
// ---------------------------------------------------------------------------

/**
 * Palette colours are ordinary custom properties on <html>, so a component CAN
 * write `bg-[hsl(var(--brand))]` and it will render — and follow the palette —
 * while skipping the role layer. Then "change which colour plays which part by
 * editing a role" silently stops being true for that element. ADR-402 says only
 * roles point at a palette; this is what checks it (LP-901 review).
 */
const FRONTEND = new URL("../../", import.meta.url).pathname;
/** The two places a palette name belongs: the roles, and the palettes themselves. */
const ROLE_LAYER = join(FRONTEND, "app/globals.css");
const PALETTE_DIR = join(FRONTEND, "app/palettes");

const PALETTE_NAME = new RegExp(`(?<![\\w-])(?:${COLOUR_NAMES.join("|")})(?![\\w-])`, "g");

function consumerFiles(): string[] {
  const walk = (dir: string): string[] =>
    readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
      const path = join(dir, entry.name);
      if (path === ROLE_LAYER || path === PALETTE_DIR) return [];
      if (entry.isDirectory()) return entry.name === "node_modules" ? [] : walk(path);
      return /\.(tsx?|css)$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name) ? [path] : [];
    });
  // Derived from the tree, like design-tokens.test.ts, so a new directory is
  // scanned without anyone remembering to add it.
  return readdirSync(FRONTEND, { withFileTypes: true })
    .filter((e) => e.isDirectory() && !e.name.startsWith(".") && e.name !== "node_modules")
    .flatMap((e) => walk(join(FRONTEND, e.name)));
}

/**
 * Code only: a palette name quoted in a comment is documentation, not a use.
 * Comments are blanked rather than removed, so reported line numbers stay true.
 */
function codeOnly(source: string): string {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, (comment) => comment.replace(/[^\n]/g, ""))
    .split("\n")
    .map((line) => (line.trim().startsWith("//") ? "" : line))
    .join("\n");
}

describe("only the role layer names a palette colour", () => {
  it("scans the whole tree, and knows a palette name when it sees one", () => {
    // The controls: an empty scan, or a pattern that matches nothing, is green.
    const files = consumerFiles();
    expect(files.some((f) => f.endsWith("components/status-token.tsx"))).toBe(true);
    expect(files).not.toContain(ROLE_LAYER);
    expect(files.some((f) => f.startsWith(`${PALETTE_DIR}/`))).toBe(false);
    expect("bg-[hsl(var(--brand))]".match(PALETTE_NAME)).toEqual(["--brand"]);
    expect("hsl(var(--neutral-10) / 0.5)".match(PALETTE_NAME)).toEqual(["--neutral-10"]);
    expect("var(--primary) var(--brand-new) var(--reduce)".match(PALETTE_NAME)).toBeNull();
  });

  it("finds none outside globals.css and app/palettes/", () => {
    const offenders: string[] = [];
    for (const file of consumerFiles()) {
      for (const [index, line] of codeOnly(readFileSync(file, "utf8")).split("\n").entries()) {
        for (const [name] of line.matchAll(PALETTE_NAME)) {
          offenders.push(`${file.slice(FRONTEND.length)}:${index + 1} ${name}`);
        }
      }
    }
    expect(offenders, "use the role (bg-primary, text-warning), not the palette colour").toEqual(
      [],
    );
  });
});
