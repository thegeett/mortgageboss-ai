/**
 * The banned phrases stay banned (LP-UI-034).
 *
 * "Something went wrong" is an apology in the place where information belongs:
 * it names nothing, explains nothing, and leaves a processor with no next move.
 * The ticket bans it by name, and it had spread to eight places — including the
 * shared `GENERIC_MESSAGE` that produced it everywhere else, and two call sites
 * that string-matched against it in order to replace it.
 *
 * A source scan rather than a render, for the same reason `form-control-zoom`
 * scans: the thing that must not happen is a NEW screen reintroducing it, and no
 * render test covers a screen nobody has written yet.
 */
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * Phrases that say nothing. Each is banned for its own reason:
 * - "something went wrong" — names nothing.
 * - "an error occurred" / "unexpected error" — restates that there is an error.
 * - "please try again" ALONE is fine as a closing instruction; it is banned only
 *   as the whole message, which is why it is not listed here.
 */
const BANNED = [/something went wrong/i, /an error occurred/i, /an unexpected error/i];

const ROOT = new URL("../../", import.meta.url).pathname;

/** Not source: dependencies, build output, static assets. */
const NOT_SOURCE = new Set(["node_modules", "public", "coverage"]);

/**
 * Every top-level directory that holds source, DERIVED rather than listed.
 *
 * The listed version was `["app", "components", "lib"]` and silently missed
 * `hooks/` — six files including `use-require-auth`, which is exactly the kind of
 * place a toast message gets written. A ban guard that does not scan somewhere is
 * indistinguishable from one that scans it and finds nothing, and the whole point
 * of this test is the file nobody has written yet. Verified by planting the phrase
 * in `hooks/`: the listed version stayed green.
 */
function searchRoots(): string[] {
  return readdirSync(ROOT, { withFileTypes: true })
    .filter((e) => e.isDirectory() && !e.name.startsWith(".") && !NOT_SOURCE.has(e.name))
    .map((e) => e.name);
}

function sourceFiles(): string[] {
  const walk = (dir: string): string[] =>
    readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
      const path = join(dir, entry.name);
      if (entry.isDirectory()) return entry.name === "node_modules" ? [] : walk(path);
      return /\.tsx?$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name) ? [path] : [];
    });
  return searchRoots().flatMap((dir) => walk(join(ROOT, dir)));
}

/**
 * The lines of a file that are NOT comments.
 *
 * Block-aware, because a single-line check is not enough: a JSX comment
 * explaining why a phrase is banned legitimately quotes it, and its continuation
 * lines start with the quote rather than with `*`. A guard that reported those
 * would push authors into not explaining themselves, which is the opposite of
 * what it is for.
 */
function codeLines(source: string): Array<[number, string]> {
  const out: Array<[number, string]> = [];
  let inBlock = false;
  source.split("\n").forEach((line, index) => {
    // STRIP the commented spans rather than dropping the whole line. Dropping it
    // skipped any code that shared a line with a comment, and
    // `/* note */ const m = "Something went wrong";` is a line a formatter can
    // produce — the guard read it as a comment and reported nothing.
    let rest = line;
    let code = "";
    for (;;) {
      if (inBlock) {
        const close = rest.indexOf("*/");
        if (close === -1) break;
        rest = rest.slice(close + 2);
        inBlock = false;
        continue;
      }
      const open = rest.indexOf("/*");
      if (open === -1) {
        code += rest;
        break;
      }
      code += rest.slice(0, open);
      rest = rest.slice(open + 2);
      inBlock = true;
    }
    // A `//` comment is skipped only when it is the WHOLE line. A trailing one is
    // still scanned, which can over-report — the safe direction for a ban, and
    // cheaper than deciding whether a `//` sits inside a string literal.
    if (code.trim().startsWith("//")) return;
    if (code.trim().length > 0) out.push([index + 1, code]);
  });
  return out;
}

describe("no apology stands in for information", () => {
  it("scans a real set of files", () => {
    // The positive control. Every assertion below passes over an empty list.
    const files = sourceFiles();
    expect(files.length).toBeGreaterThan(100);
    expect(files.some((f) => f.endsWith("error-state.tsx"))).toBe(true);
  });

  it("sees code and skips comments", () => {
    // The control for `codeLines` itself. Without this, a bug that treated every
    // line as a comment would make the scan below pass over nothing.
    const sample = ["const a = 1;", "// banned here", "/*", "banned", "*/", "const b = 2;"].join(
      "\n",
    );
    expect(codeLines(sample).map(([, line]) => line)).toEqual(["const a = 1;", "const b = 2;"]);
  });

  it("scans every directory that holds source, not a remembered three", () => {
    // `hooks/` was missed by the listed version. Asserted by NAME because the
    // failure is silent: a phrase planted there stayed green through the whole
    // suite, and no other assertion here can tell "scanned and clean" from
    // "never looked".
    expect(searchRoots()).toContain("hooks");
    expect(sourceFiles().some((f) => f.includes("/hooks/"))).toBe(true);
  });

  it("keeps the code that shares a line with a comment", () => {
    // The false negative in the old `codeLines`: a line OPENING a block comment
    // was dropped whole, so anything after the `*/` went unscanned.
    const sample = '/* note */ const m = "Something went wrong";';
    expect(codeLines(sample)).toHaveLength(1);
    expect(BANNED.some((p) => p.test(codeLines(sample)[0]?.[1] ?? ""))).toBe(true);
  });

  it("still skips a phrase quoted inside a block comment", () => {
    // The other direction, and the reason `codeLines` exists: a comment must be
    // able to explain the ban by quoting it.
    const sample = ["/**", " * We never say 'Something went wrong'.", " */", "const a = 1;"].join(
      "\n",
    );
    expect(codeLines(sample).map(([, line]) => line.trim())).toEqual(["const a = 1;"]);
  });

  it("no user-facing string says 'something went wrong'", () => {
    const offenders: string[] = [];
    for (const file of sourceFiles()) {
      for (const [lineNumber, line] of codeLines(readFileSync(file, "utf8"))) {
        if (BANNED.some((pattern) => pattern.test(line))) {
          offenders.push(`${file.replace(ROOT, "")}:${lineNumber}  ${line.trim().slice(0, 90)}`);
        }
      }
    }
    expect(offenders, "an error must name what failed and the way out").toEqual([]);
  });
});
