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

/**
 * ANY text colour utility with an opacity modifier.
 *
 * It named three tokens and there are more in use — `text-primary/80` and
 * `text-background/75` were both in the tree and neither was looked at. Both
 * measure fine today, which is the point: nothing was checking, and a list of
 * three tokens is a list of the three somebody remembered. Sizes (`text-sm`) and
 * alignment (`text-left`) are excluded by requiring a `/opacity` suffix, which
 * only colour utilities take.
 *
 * THE LOOKBEHIND EXCLUDED `:`, so every variant-prefixed utility was invisible —
 * `hover:text-muted-foreground/80`, `dark:text-foreground/50` and
 * `md:text-foreground-2/60` all went unseen by the version that named the right
 * three tokens. A colon is how a variant attaches, so excluding it excludes the
 * variants. Word characters and `-` still bar a mid-token match (`subtext-…`).
 */
const FADED_TEXT = /(?<![\w-])!?text-[a-z][a-z0-9-]*\/\d+/g;

/**
 * Faded text that has been MEASURED and passes, with the surface it was measured
 * against. Everything else is an offender.
 *
 * An exception here is a claim about a specific pairing, so it carries the number.
 * A token's real ratio depends on what is behind it, which no static scan knows —
 * so the scan bans the shape and a person measures the exception, rather than the
 * scan trying to guess a surface.
 */
const MEASURED_SAFE: Record<string, string> = {
  // Used only inside `TooltipContent`, which is `bg-foreground`. Fading the
  // BACKGROUND token on an inverted surface moves it away from that surface, not
  // towards it — the opposite of the hazard this test exists for.
  "text-background/75": "10.30:1 on bg-foreground (measured 2026-08-30)",
  // A hover state on `bg-card`; the resting `text-primary` is 8.55:1.
  "text-primary/80": "5.10:1 on bg-card (measured 2026-08-30)",
};

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

  it("catches a faded token the three-name list did not know about", () => {
    // The tree already contained two the list did not name.
    expect("text-destructive/70".match(FADED_TEXT)).toEqual(["text-destructive/70"]);
  });

  it("catches a faded token behind a VARIANT, which the lookbehind excluded", () => {
    // The larger of the two gaps, and independent of the token list: the old
    // lookbehind barred a preceding `:`, which is exactly how a variant attaches.
    // Every hover, focus, dark and breakpoint variant was unseen.
    expect("hover:text-muted-foreground/80".match(FADED_TEXT)).toEqual([
      "text-muted-foreground/80",
    ]);
    expect("dark:text-foreground/50".match(FADED_TEXT)).toEqual(["text-foreground/50"]);
    expect("md:text-foreground-2/60".match(FADED_TEXT)).toEqual(["text-foreground-2/60"]);
  });

  it("still does not match inside a longer word", () => {
    expect("subtext-foreground/50".match(FADED_TEXT)).toBeNull();
  });

  it("does not catch a size or an alignment", () => {
    // The reason the wider pattern is safe: only a colour utility takes `/opacity`.
    for (const cls of ["text-sm", "text-left", "text-xs font-medium", "text-[11px]"]) {
      expect(cls.match(FADED_TEXT)).toBeNull();
    }
  });

  it("every measured exception is still in the tree", () => {
    // A stale exemption is an unexamined claim — it says a pairing was measured
    // when the pairing no longer exists.
    const all = sourceFiles()
      .map((f) => readFileSync(f, "utf8"))
      .join("\n");
    for (const utility of Object.keys(MEASURED_SAFE)) {
      expect(all, `${utility} is exempted but no longer used`).toContain(utility);
    }
  });

  it("finds none in the app", () => {
    const offenders: string[] = [];
    for (const file of sourceFiles()) {
      for (const [index, line] of readFileSync(file, "utf8").split("\n").entries()) {
        for (const hit of line.match(FADED_TEXT) ?? []) {
          if (hit in MEASURED_SAFE) continue;
          offenders.push(`${file.replace(ROOT, "")}:${index + 1}  ${hit}`);
        }
      }
    }
    expect(
      offenders,
      "measure it against the surface it sits on; if it passes, record the ratio in MEASURED_SAFE",
    ).toEqual([]);
  });
});
