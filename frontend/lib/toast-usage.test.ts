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

/** Every syntax that pulls the module in. Quotes either way — lint prefers double,
 *  and a guard should not depend on lint having run. */
const REACHES_SONNER = [
  /from\s+["']sonner["']/,
  /import\s*\(\s*["']sonner["']\s*\)/,
  /require\s*\(\s*["']sonner["']\s*\)/,
];

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
        // EVERY way in, not just the one the 49 call sites happened to use. A
        // static `from "sonner"` was the only shape checked; `await
        // import("sonner")` and `require("sonner")` both reached Sonner and both
        // left the guard green. A ban that names one syntax bans one syntax.
        if (REACHES_SONNER.some((pattern) => pattern.test(source))) {
          offenders.push(`${relative} reaches sonner directly`);
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

describe("the ban covers every way in", () => {
  /**
   * The scan matched a static `from "sonner"` and nothing else, so
   * `await import("sonner")` and `require("sonner")` both reached Sonner with the
   * guard green — verified by planting each in a real component. A ban that names
   * one syntax bans one syntax.
   */
  const reaches = (source: string) => REACHES_SONNER.some((p) => p.test(source));

  it.each([
    ['import { toast } from "sonner";', "static import"],
    ["import { toast } from 'sonner';", "static import, single quotes"],
    ['const { toast } = await import("sonner");', "dynamic import"],
    ['const { toast } = require("sonner");', "require"],
    ['import * as sonner from "sonner";', "namespace import"],
  ])("catches %s (%s)", (source) => {
    expect(reaches(source)).toBe(true);
  });

  it.each([
    ['import { notifySuccess } from "@/lib/toast";', "the wrapper"],
    ["// we do not import sonner here", "a mention in a comment is not a match"],
    ['import { Toaster } from "sonner-lite";', "a different package"],
  ])("does not catch %s (%s)", (source) => {
    expect(reaches(source)).toBe(false);
  });
});
