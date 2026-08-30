import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { CALCULATOR_GRID, CALCULATOR_RESULT_COLUMN } from "./layout";

const ROOT = new URL("../../../", import.meta.url).pathname;

/**
 * The three calculators lay out the same way, from one definition (LP-UI-045 review).
 *
 * DTI, LTV and the generic card each wrote the grid and the sticky result column
 * out in full, and only DTI had a test — so the other two were the same string in
 * two more files with nothing comparing them. A shared constant is only worth
 * something if nothing goes back to writing the literal, which is what this scans
 * for.
 */
function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return entry.name === "node_modules" ? [] : sourceFiles(path);
    return /\.tsx?$/.test(entry.name) ? [path] : [];
  });
}

describe("the calculator layout has one definition", () => {
  const LAYOUT_MODULE = "components/file/calculators/layout.ts";

  it("states the shape it is meant to state", () => {
    // The control: a broken constant would make the scan below pass over nothing.
    expect(CALCULATOR_GRID).toContain("lg:grid-cols-");
    expect(CALCULATOR_RESULT_COLUMN).toContain("lg:sticky");
  });

  it.each([
    ["the grid", CALCULATOR_GRID],
    ["the result column", CALCULATOR_RESULT_COLUMN],
  ])("no file re-writes %s as a literal", (_label, literal) => {
    const offenders = sourceFiles(join(ROOT, "components"))
      .filter((file) => !file.endsWith("layout.ts") && !/\.test\.tsx?$/.test(file))
      .filter((file) => readFileSync(file, "utf8").includes(literal))
      .map((file) => file.replace(ROOT, ""));
    expect(offenders, `import it from ${LAYOUT_MODULE} instead`).toEqual([]);
  });
});
