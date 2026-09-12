/**
 * A component that nothing but its own test renders (LP-849 review).
 *
 * THE FIFTH INSTANCE OF ONE DEFECT. LP-840 invalidated a query key no component read. LP-845
 * registered a broadcast listener no client installed. LP-848's staleness heal was called by no read
 * path, and its regeneration guard protected one of five entrances. LP-849's editor sat behind
 * `next/dynamic` with `ssr: false`, which renders a placeholder forever if the import is wrong, while
 * every dialog test read the body from the seeded detail and passed either way.
 *
 * `backend/tests/test_unwired_services.py` catches the service version. This is the component version,
 * and it is the half the ticket asked for: a test renders a component directly, which is exactly what
 * production is failing to do, so "its tests pass" carries no information about whether anything
 * shows it to a person.
 *
 * WHAT IS DELIBERATELY NOT SCANNED, because it would be noise rather than signal:
 *
 * - **Next route files.** A route's `page.tsx` and its siblings are wired by FILENAME. Nothing imports a
 *   page, and nothing should; including them reported twenty false orphans.
 * - **Use inside its own module.** A sub-component rendered by the exported one beside it is wired.
 *   Counting only cross-file imports reported seven more false orphans, all of them ordinary React.
 *
 * WHAT IT CANNOT SEE: a component imported and then rendered only in a branch nothing reaches. Being
 * imported is the floor this checks, not the ceiling.
 */

import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const ROOT = process.cwd();

/** Next's file-convention modules, wired by name rather than by an import. */
const CONVENTION = new Set([
  "page.tsx",
  "layout.tsx",
  "loading.tsx",
  "error.tsx",
  "not-found.tsx",
  "template.tsx",
  "default.tsx",
]);

function walk(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return entry.name === "node_modules" ? [] : walk(path);
    return /\.tsx?$/.test(entry.name) ? [path] : [];
  });
}

const ALL = ["components", "app", "lib"].flatMap((d) => walk(join(ROOT, d)));
const IS_TEST = (path: string) => /\.test\.tsx?$/.test(path);
const PRODUCTION = ALL.filter((p) => !IS_TEST(p));
const TESTS = ALL.filter(IS_TEST);
const SOURCE = new Map(ALL.map((p) => [p, readFileSync(p, "utf8")]));

/** Exported PascalCase functions under `components/`, excluding Next's route files. */
function exportedComponents(): Map<string, string> {
  const found = new Map<string, string>();
  for (const path of PRODUCTION) {
    if (!path.startsWith(join(ROOT, "components"))) continue;
    if (CONVENTION.has(path.split("/").pop() ?? "")) continue;
    for (const match of (SOURCE.get(path) ?? "").matchAll(
      /^export (?:default )?function ([A-Z]\w*)/gm,
    )) {
      if (!found.has(match[1] ?? "")) found.set(match[1] ?? "", path);
    }
  }
  return found;
}

function usedBy(paths: string[], name: string, own: string, countOwnFile: boolean): boolean {
  const pattern = new RegExp(`\\b${name}\\b`, "g");
  for (const path of paths) {
    const source = SOURCE.get(path) ?? "";
    if (path === own) {
      // More than once means the definition AND at least one use beside it.
      if (countOwnFile && (source.match(pattern) ?? []).length > 1) return true;
      continue;
    }
    if (pattern.test(source)) return true;
    pattern.lastIndex = 0;
  }
  return false;
}

function unwired(): { testOnly: string[]; unused: string[] } {
  const testOnly: string[] = [];
  const unused: string[] = [];
  for (const [name, own] of exportedComponents()) {
    if (usedBy(PRODUCTION, name, own, true)) continue;
    (usedBy(TESTS, name, own, false) ? testOnly : unused).push(name);
  }
  return { testOnly: testOnly.sort(), unused: unused.sort() };
}

/**
 * Components nothing renders, as of the LP-849 review. One comes OFF this list when something uses
 * it, and goes ON it only with a reason — which is the mechanism.
 */
const KNOWN_UNWIRED = {
  // An `aria-busy` wrapper from LP-47 that no screen ever used. Left alone by this review rather than
  // deleted: it predates these tickets by a long way, and removing it is a cleanup, not a review fix.
  testOnly: ["LoadingRegion"],
  unused: [] as string[],
};

describe("no component is wired to nothing", () => {
  it("nothing new is rendered only by its own test", () => {
    const { testOnly } = unwired();
    expect(testOnly.filter((n) => !KNOWN_UNWIRED.testOnly.includes(n))).toEqual([]);
    // The other direction, so the list cannot rot into a fiction describing nothing.
    expect(KNOWN_UNWIRED.testOnly.filter((n) => !testOnly.includes(n))).toEqual([]);
  });

  it("and nothing is rendered by nothing at all", () => {
    expect(unwired().unused).toEqual(KNOWN_UNWIRED.unused);
  });

  it("the scan itself works", () => {
    // THE POSITIVE CONTROL, both ends. The assertions above are satisfied by a scan that finds no
    // components and by one that finds every component orphaned.
    const components = exportedComponents();
    expect(components.size).toBeGreaterThan(80);
    // MessageEditor is reached ONLY through `next/dynamic`'s import callback, which is the case most
    // likely to read as unwired — and the case this whole file exists for.
    expect(components.has("MessageEditor")).toBe(true);
    expect(unwired().testOnly).not.toContain("MessageEditor");
    // And the one known orphan is genuinely detected, not assumed.
    expect(unwired().testOnly).toContain("LoadingRegion");
  });
});
