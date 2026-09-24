import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

/**
 * The radius split lives in two lines, and everything else inherits it.        LP-909 review
 * ===========================================================================
 * CLAUDE.md: 5px controls, 8px containers (`--radius` / `--radius-container`),
 * and it names the mistake it invites — "a panel is not a button: `rounded-md`
 * is the control radius, and reaching for it on a card is the mistake it
 * invites".
 *
 * WHY THIS GUARDS THE PRIMITIVES AND NOT THE TREE. A tree-wide scan was
 * considered and rejected with the numbers: 73 `rounded-md` occurrences, 51 of
 * them on a line that also names a container signal — and reading them shows
 * inputs and textareas, which are CONTROLS and correctly 5px. The verdict
 * depends on what the element IS, and no regex over class strings knows that.
 * A guard with that false-positive rate is worse than the gap, because it lets
 * someone say "scanned and clean" when the scan cannot tell.
 *
 * `design-tokens.test.ts` can scan the tree because a Tailwind palette scale is
 * wrong UNCONDITIONALLY — the token decides alone. Radius has no such property.
 *
 * SO THE STRATEGY IS COMPOSITIONAL: build containers from `Card` and controls
 * from `Button`, and the radius is correct by construction. This file guards the
 * two lines that strategy rests on. One edit to `card.tsx` would silently give
 * every card in the app the control radius with every other test still green —
 * the same shape as an index that lived in the migration and not the model.
 *
 * Two assertions over two files: no element-type inference, no false positives.
 */

/** Read a sibling primitive. Resolved from this file so it survives the suite's cwd. */
function source(file: string): string {
  const text = readFileSync(new URL(`./${file}`, import.meta.url).pathname, "utf8");
  // ⚠️ A GUARD, NOT CEREMONY. An unreadable or emptied file would make every assertion below pass
  // against nothing — `expect("").not.toMatch(...)` is true. That failure mode has cost this ticket
  // four assertions already.
  expect(text.length, `${file} is empty or unreadable`).toBeGreaterThan(200);
  return text;
}

/**
 * Class strings only. A radius named in prose is documentation — this very file's docstring quotes
 * `rounded-md`, and a naive read of `card.tsx` would one day do the same.
 */
function codeOnly(text: string): string {
  return text
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .split("\n")
    .filter((line) => !line.trim().startsWith("//"))
    .join("\n");
}

describe("the radius split is fixed at the primitives", () => {
  it("Card carries the CONTAINER radius", () => {
    const card = codeOnly(source("card.tsx"));
    expect(card).toMatch(/\brounded-lg\b/);
    expect(card, "a card given the control radius makes every panel in the app 5px").not.toMatch(
      /\brounded-md\b/,
    );
  });

  it("Button carries the CONTROL radius", () => {
    const button = codeOnly(source("button.tsx"));
    expect(button).toMatch(/\brounded-md\b/);
    expect(button, "a button given the container radius makes every control 8px").not.toMatch(
      /\brounded-lg\b/,
    );
  });

  it("does not read a radius out of a comment", () => {
    // ⚠️ THE POSITIVE CONTROL. Without it, a `codeOnly` that silently returned "" would make both
    // tests above pass — the not-toMatch halves trivially, and the toMatch halves would fail, so
    // this specifically pins that stripping works rather than that it is total.
    const withComment = codeOnly('// rounded-md in prose\nconst x = "rounded-lg";');
    expect(withComment).not.toMatch(/\brounded-md\b/);
    expect(withComment).toMatch(/\brounded-lg\b/);
  });
});
