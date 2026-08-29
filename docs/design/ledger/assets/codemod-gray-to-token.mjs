#!/usr/bin/env node
/**
 * LEDGER — gray-* to design tokens                                   LP-UI-004
 * =============================================================================
 * 784 hardcoded `gray-*` classes across 67 of 95 components bypass the token
 * layer entirely. That is why `darkMode: ["class"]` has never been switchable,
 * and why swapping globals.css alone would only half-work.
 *
 * It also fixes a real accessibility failure on the way through: `text-gray-400`
 * (178 uses, the most-used text colour in the app) sits at 2.54:1 on white — it
 * fails AA for text and fails even the 3:1 bar for icons. Everything in the
 * 300-500 band lands on --muted-foreground at 4.56:1.
 *
 * Usage
 *   node docs/design/ledger/assets/codemod-gray-to-token.mjs --dry   # report only
 *   node docs/design/ledger/assets/codemod-gray-to-token.mjs         # write
 *
 * Then: pnpm biome check --write . && pnpm tsc --noEmit && pnpm test
 * Review the diff as ONE commit. It is mechanical; anything surprising in it is
 * a real finding, not codemod noise.
 */
import { readFileSync, writeFileSync } from "node:fs";
import { readdirSync, statSync } from "node:fs";
import { join, extname } from "node:path";

const ROOTS = ["app", "components", "lib"];
const DRY = process.argv.includes("--dry");

/**
 * property -> shade -> token.
 *
 * Three text tones, not six. Hierarchy in this system comes from size, colour
 * and space, so 900/800 collapse to `foreground`, 700/600 to `foreground-2`,
 * and everything from 500 down to `muted-foreground`. A caption is not made
 * quieter by being lighter than the AA floor; it is made illegible.
 */
const MAP = {
  text: {
    950: "foreground", 900: "foreground", 800: "foreground",
    700: "foreground-2", 600: "foreground-2",
    500: "muted-foreground", 400: "muted-foreground", 300: "muted-foreground",
  },
  bg: {
    50: "muted", 100: "muted", 200: "border", 300: "border",
    800: "foreground", 900: "foreground", 950: "foreground",
  },
  border: {
    100: "border", 200: "border", 300: "input", 400: "input",
  },
  divide: { 100: "border", 200: "border", 300: "border" },
  ring: { 200: "border", 300: "input", 400: "input" },
  fill: {
    900: "foreground", 700: "foreground-2", 600: "foreground-2",
    500: "muted-foreground", 400: "muted-foreground", 300: "muted-foreground",
  },
  stroke: {
    900: "foreground", 700: "foreground-2", 600: "foreground-2",
    500: "muted-foreground", 400: "muted-foreground", 300: "muted-foreground",
  },
  placeholder: { 300: "muted-foreground", 400: "muted-foreground", 500: "muted-foreground" },
};

// Optional Tailwind variants (hover:, focus-visible:, group-hover:, dark:, sm:, [&>x]: …)
const PATTERN =
  /((?:(?:[a-z0-9[\]&>_.:-]+):)*)\b(text|bg|border|divide|ring|fill|stroke|placeholder)-gray-(\d{2,3})(\/\d{1,3})?\b/g;

function walk(dir, out = []) {
  for (const entry of readdirSync(dir)) {
    if (entry === "node_modules" || entry === ".next") continue;
    const p = join(dir, entry);
    if (statSync(p).isDirectory()) walk(p, out);
    else if ([".ts", ".tsx"].includes(extname(p))) out.push(p);
  }
  return out;
}

const unmapped = new Map();
const perClass = new Map();
let filesChanged = 0;
let replacements = 0;

for (const root of ROOTS) {
  let files;
  try {
    files = walk(root);
  } catch {
    console.error(`skip: ${root} not found — run this from the frontend/ directory`);
    continue;
  }
  for (const file of files) {
    const before = readFileSync(file, "utf8");
    const after = before.replace(PATTERN, (whole, variants, prop, shade, alpha) => {
      const token = MAP[prop]?.[Number(shade)];
      if (!token) {
        unmapped.set(whole, (unmapped.get(whole) ?? 0) + 1);
        return whole;
      }
      const key = `${prop}-gray-${shade} -> ${prop}-${token}`;
      perClass.set(key, (perClass.get(key) ?? 0) + 1);
      replacements += 1;
      return `${variants}${prop}-${token}${alpha ?? ""}`;
    });
    if (after !== before) {
      filesChanged += 1;
      if (!DRY) writeFileSync(file, after);
    }
  }
}

const w = (s, n) => String(s).padEnd(n);
console.log(`\n${DRY ? "DRY RUN — nothing written" : "WROTE CHANGES"}\n`);
console.log(`  files changed   ${filesChanged}`);
console.log(`  replacements    ${replacements}\n`);
console.log("  mapping applied");
for (const [k, n] of [...perClass.entries()].sort((a, b) => b[1] - a[1])) {
  console.log(`    ${w(n, 5)} ${k}`);
}
if (unmapped.size) {
  console.log("\n  NOT MAPPED — decide these by hand:");
  for (const [k, n] of [...unmapped.entries()].sort((a, b) => b[1] - a[1])) {
    console.log(`    ${w(n, 5)} ${k}`);
  }
} else {
  console.log("\n  nothing left unmapped.");
}

// Verified against the repo on 2026-08-29: 811 replacements across 70 files,
// with exactly three left over. Both sites are INVERTED surfaces (a dark
// tooltip sitting on a light page), which no colour-shade mapping can decide
// correctly. Fix them by hand as part of LP-UI-004:
//
//   components/ui/tooltip.tsx
//     border-gray-700 bg-gray-900 text-gray-100
//     -> border-foreground bg-foreground text-background
//     (inverts correctly in dark mode too: a tooltip should contrast with the
//      page it floats over, not match it)
//
//   components/file/ltv/ltv-calculator.tsx:240
//     text-gray-200  ->  text-background     (it sits on that same dark panel)
console.log("");
