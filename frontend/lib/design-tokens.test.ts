import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * Colour comes from tokens, never from Tailwind's palette (LP-UI-004).
 *
 * THE CODEMOD HAD NO GUARD, which is why this file exists. LP-UI-004 replaced 803
 * ad-hoc greys across 70 files and left nothing to keep them out — so merging the
 * bedrock branch reintroduced 27 of them, in files the codemod had never seen,
 * with every test green.
 *
 * It is not a style preference. `--card` flips in dark mode and `gray-900` does
 * not, so the DTI ungate dialog's labels and figures measured **1.01:1** against
 * the dark card — invisible, not merely off-palette. `bg-white` is the same
 * defect for a surface.
 *
 * A one-time codemod fixes the tree it ran over. This fixes the next one.
 */
const ROOT = new URL("../", import.meta.url).pathname;

/** A Tailwind palette colour, which by definition does not respond to the theme. */
const PALETTE = new RegExp(
  String.raw`(?<![\w-])(?:text|bg|border|ring|divide|placeholder|from|via|to|decoration|outline|shadow|accent|caret|fill|stroke)-` +
    String.raw`(?:gray|slate|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose)-\d{2,3}` +
    String.raw`(?![\w-])`,
  "g",
);

/** A literal surface. Same defect as a palette grey: it cannot flip. */
const LITERAL_SURFACE = /(?<![\w-])(?:bg|text|border)-white(?![\w-])/g;

/**
 * `bg-black/NN` on a modal scrim is correct and deliberate — the overlay behind a
 * dialog is a shade of the world, not a themed surface, and shadcn ships it that
 * way in both themes. Listed rather than pattern-matched so a new one is a
 * decision somebody makes.
 */
const ALLOWED = new Set(["components/ui/dialog.tsx", "components/ui/sheet.tsx"]);

function sourceFiles(): string[] {
  const walk = (dir: string): string[] =>
    readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
      const path = join(dir, entry.name);
      if (entry.isDirectory()) return entry.name === "node_modules" ? [] : walk(path);
      return /\.tsx?$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name) ? [path] : [];
    });
  // Derived from the tree, not a listed set of directories: a hand-written list
  // cannot tell "scanned and clean" from "never looked" (LP-UI-034 review).
  return readdirSync(ROOT, { withFileTypes: true })
    .filter((e) => e.isDirectory() && !e.name.startsWith(".") && e.name !== "node_modules")
    .flatMap((e) => {
      try {
        return walk(join(ROOT, e.name));
      } catch {
        return [];
      }
    });
}

/** Class strings only — a palette name quoted in a comment is documentation. */
function codeOnly(source: string): string {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .split("\n")
    .filter((line) => !line.trim().startsWith("//"))
    .join("\n");
}

describe("colour comes from the design tokens", () => {
  it("scans the whole tree", () => {
    // The positive control: every assertion below passes over an empty list.
    const files = sourceFiles();
    expect(files.length).toBeGreaterThan(100);
    expect(files.some((f) => f.includes("/components/ui/"))).toBe(true);
  });

  it("catches a palette colour when there is one", () => {
    // The control for the pattern itself.
    expect("text-gray-400".match(PALETTE)).toEqual(["text-gray-400"]);
    expect("border-gray-200 p-2".match(PALETTE)).toEqual(["border-gray-200"]);
    expect("hover:text-red-500".match(PALETTE)).toEqual(["text-red-500"]);
    // And does not fire on the tokens, or on a size that merely looks similar.
    expect("text-muted-foreground text-sm border-border".match(PALETTE)).toBeNull();
  });

  it("uses no Tailwind palette colour", () => {
    const offenders: string[] = [];
    for (const file of sourceFiles()) {
      const relative = file.replace(ROOT, "");
      if (ALLOWED.has(relative)) continue;
      for (const [index, line] of codeOnly(readFileSync(file, "utf8")).split("\n").entries()) {
        for (const hit of line.match(PALETTE) ?? []) {
          offenders.push(`${relative}:${index + 1}  ${hit}`);
        }
      }
    }
    expect(
      offenders,
      "a palette colour does not flip in dark mode — use the token (text-foreground, " +
        "text-foreground-2, text-muted-foreground, border-border, bg-muted, bg-card)",
    ).toEqual([]);
  });

  it("paints no literal white surface", () => {
    const offenders: string[] = [];
    for (const file of sourceFiles()) {
      const relative = file.replace(ROOT, "");
      if (ALLOWED.has(relative)) continue;
      for (const [index, line] of codeOnly(readFileSync(file, "utf8")).split("\n").entries()) {
        for (const hit of line.match(LITERAL_SURFACE) ?? []) {
          offenders.push(`${relative}:${index + 1}  ${hit}`);
        }
      }
    }
    expect(offenders, "bg-white stays white in dark mode — bg-card is the surface").toEqual([]);
  });
});
