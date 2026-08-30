/**
 * Nothing calls Sonner directly (LP-UI-035).
 *
 * The wrapper's whole job is to require the second line — the consequence on a
 * success, the next move on an error. A call that goes round it can still write
 * "Asset added" and nothing else, which is where all 49 call sites started.
 *
 * A source scan, for the reason `no-apology` scans: what must not happen is a NEW
 * call site reaching for `toast.success` again, and no render test covers a screen
 * nobody has written yet.
 *
 * Roots are derived from the tree rather than listed, because the LP-UI-034 review
 * found `hooks/` missing from a hand-written list and the suite stayed green over
 * a planted violation. An authored coverage list cannot tell "scanned and clean"
 * from "never looked".
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const ROOT = new URL("../", import.meta.url).pathname;

/** Where app source lives — every top-level directory that holds .ts/.tsx. */
function sourceRoots(): string[] {
  return readdirSync(ROOT, { withFileTypes: true })
    .filter((e) => e.isDirectory() && !e.name.startsWith(".") && e.name !== "node_modules")
    .map((e) => join(ROOT, e.name))
    .filter((dir) => hasSource(dir));
}

function hasSource(dir: string): boolean {
  try {
    return walk(dir).length > 0;
  } catch {
    return false;
  }
}

function walk(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return entry.name === "node_modules" ? [] : walk(path);
    return /\.tsx?$/.test(entry.name) ? [path] : [];
  });
}

/**
 * The wrapper, and the one place the Toaster is mounted and styled.
 *
 * TEST FILES ARE EXEMPT rather than listed: a test that mocks the `sonner` module
 * is mocking it for the wrapper's benefit, which is the correct thing to do and
 * has nothing to do with a component reaching past the wrapper.
 */
const ALLOWED = ["lib/toast.ts", "components/providers.tsx"];

describe("every toast goes through the wrapper", () => {
  it("scans the whole tree, not a list of directories", () => {
    // The positive control, and the LP-UI-034 lesson: a missing directory is
    // indistinguishable from a clean one unless something asserts coverage.
    const roots = sourceRoots().map((r) => r.replace(ROOT, ""));
    expect(roots).toContain("app");
    expect(roots).toContain("components");
    expect(roots).toContain("lib");
    expect(roots).toContain("hooks");
  });

  it("no file calls sonner's toast directly", () => {
    const offenders: string[] = [];
    for (const dir of sourceRoots()) {
      for (const file of walk(dir)) {
        const relative = file.replace(ROOT, "");
        if (ALLOWED.includes(relative) || /\.test\.tsx?$/.test(relative)) continue;
        const source = readFileSync(file, "utf8");
        if (/from "sonner"/.test(source)) {
          offenders.push(`${relative} imports sonner directly`);
        }
      }
    }
    expect(offenders, "use notifySuccess / notifyError / notifyStarted from @/lib/toast").toEqual(
      [],
    );
  });

  it("finds files at all", () => {
    expect(sourceRoots().flatMap(walk).length).toBeGreaterThan(100);
  });
});
