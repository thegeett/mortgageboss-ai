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
const SEARCH = ["app", "components", "lib"];

function sourceFiles(): string[] {
  const walk = (dir: string): string[] =>
    readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
      const path = join(dir, entry.name);
      if (entry.isDirectory()) return entry.name === "node_modules" ? [] : walk(path);
      return /\.tsx?$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name) ? [path] : [];
    });
  return SEARCH.flatMap((dir) => walk(join(ROOT, dir)));
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
    const trimmed = line.trim();
    if (inBlock) {
      if (trimmed.includes("*/")) inBlock = false;
      return;
    }
    if (trimmed.startsWith("//")) return;
    // `{/*` and `/*` both open a block; a one-line `/* … */` closes immediately.
    const opens = trimmed.startsWith("/*") || trimmed.startsWith("{/*");
    if (opens) {
      if (!trimmed.includes("*/")) inBlock = true;
      return;
    }
    out.push([index + 1, line]);
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
