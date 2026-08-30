/**
 * No text token is faded with an opacity modifier (LP-UI-036).
 *
 * The palette is tuned so `text-muted-foreground` passes AA on every surface it
 * is used on. `text-muted-foreground/80` does not — it measured **3.45:1** at
 * 11.5px against the overview card, where 4.5 is required, and it read as a
 * reasonable design choice right up until something computed the ratio.
 *
 * There is no third level of quiet below muted that is still readable. Wanting
 * one is a sign the row has too many levels, not that the token needs dimming.
 *
 * Live contrast is measured in a browser (a token's real ratio depends on what is
 * behind it, which no static scan knows); this is the cheap guard that stops the
 * one mistake that scan found from coming back.
 */
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const ROOT = new URL("../", import.meta.url).pathname;

/** A text/foreground colour utility with an opacity modifier. */
const FADED_TEXT = /(?<![\w:-])!?text-(muted-foreground|foreground|foreground-2)\/\d+/g;

function sourceFiles(): string[] {
  const walk = (dir: string): string[] =>
    readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
      const path = join(dir, entry.name);
      if (entry.isDirectory()) return entry.name === "node_modules" ? [] : walk(path);
      return /\.tsx?$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name) ? [path] : [];
    });
  // Derived from the tree, not listed: a hand-written directory list cannot tell
  // "scanned and clean" from "never looked".
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

describe("text tokens are not faded", () => {
  it("scans the whole tree", () => {
    const files = sourceFiles();
    expect(files.length).toBeGreaterThan(100);
    expect(files.some((f) => f.includes("reconciliation-ledger"))).toBe(true);
  });

  it("catches a faded token when there is one", () => {
    // The control. Without it, a broken regex reads as a clean codebase.
    expect("text-muted-foreground/80".match(FADED_TEXT)).toEqual(["text-muted-foreground/80"]);
    expect("text-muted-foreground".match(FADED_TEXT)).toBeNull();
  });

  it("finds none in the app", () => {
    const offenders: string[] = [];
    for (const file of sourceFiles()) {
      for (const [index, line] of readFileSync(file, "utf8").split("\n").entries()) {
        for (const hit of line.match(FADED_TEXT) ?? []) {
          offenders.push(`${file.replace(ROOT, "")}:${index + 1}  ${hit}`);
        }
      }
    }
    expect(offenders, "the token passes AA; the faded variant does not").toEqual([]);
  });
});
