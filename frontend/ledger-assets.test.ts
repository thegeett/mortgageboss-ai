/**
 * The ledger assets must not drift from the files they seed.
 *
 * `docs/design/ledger/assets/*` are the drop-in sources TICKETS.md points
 * implementers at. Three review passes running, they were found lagging the
 * shipped files by exactly the fixes the previous pass had just landed — the
 * `CalculatorStatus` union missing `unknown` and `binding:*` (the "Binding:dti"
 * a screen reader read aloud), and `plexSerif` still italic-only. Copying an
 * asset forward reintroduces whatever it is behind on, silently, which is the
 * one failure mode a design system's reference copies must not have.
 *
 * Compared with whitespace collapsed: the assets are hand-aligned for reading
 * (globals.css lines its trailing comments up) while the shipped files are
 * Biome-formatted, and that difference is deliberate. Anything else is drift.
 */
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const ASSETS = "../docs/design/ledger/assets";

/** Asset path → the shipped file it is the reference copy of. */
const PAIRS: [string, string][] = [
  [`${ASSETS}/lib/status.ts`, "lib/status.ts"],
  [`${ASSETS}/components/status-token.tsx`, "components/status-token.tsx"],
  [`${ASSETS}/fonts.ts`, "lib/fonts.ts"],
  [`${ASSETS}/tailwind.config.ts`, "tailwind.config.ts"],
  [`${ASSETS}/globals.css`, "app/globals.css"],
];

/** Formatting is allowed to differ; nothing else is. */
function normalise(source: string): string {
  return source.replace(/\s+/g, " ").trim();
}

/**
 * Where two normalised sources first differ, with a little context either side.
 * Asserting the whole file prints both in full on failure, which buries the one
 * line that moved under two thousand characters of identical text.
 */
function firstDifference(asset: string, shipped: string): string {
  let i = 0;
  while (i < asset.length && i < shipped.length && asset[i] === shipped[i]) i++;
  const from = Math.max(0, i - 60);
  return [
    `first differs at character ${i}:`,
    `  asset:   …${asset.slice(from, i + 120)}`,
    `  shipped: …${shipped.slice(from, i + 120)}`,
  ].join("\n");
}

describe("the ledger assets match the files they seed", () => {
  it.each(PAIRS)("%s", (assetPath, shippedPath) => {
    const asset = normalise(readFileSync(new URL(assetPath, import.meta.url), "utf8"));
    const shipped = normalise(readFileSync(new URL(shippedPath, import.meta.url), "utf8"));
    // Compared as a boolean with the location in the message, rather than as two
    // strings: a failing `toBe` on a whole file is unreadable.
    expect(
      asset === shipped,
      `${assetPath} has drifted from ${shippedPath}\n${firstDifference(asset, shipped)}`,
    ).toBe(true);
  });
});
