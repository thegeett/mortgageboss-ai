import { readFileSync, readdirSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { emailBodyToHtml } from "./email-body";

/**
 * LP-844 REVIEW — EVERY TEMPLATE'S REAL SHAPE, THROUGH THE RENDERER.
 *
 * The build named this gap and left it: "nothing renders every template through this function ... the
 * result is a malformed email rather than a failing test", and it did not write the test because it
 * could not decide what correct looks like. Correct is decidable — not the prose, but the structural
 * properties below, each of which is a way the output could reach a borrower wrong.
 *
 * Read off the template FILES rather than through a server render, because the shapes this renderer
 * parses live in the files and in `$document_list`, not in the substituted values. The document block
 * below is a faithful copy of `render_document_block`'s real output, apostrophes and all.
 */
const TEMPLATES_DIR = `${process.cwd()}/../backend/app/communications/templates/`;

const DOCUMENT_LIST =
  "- Bank statements \u2014 the two most recent months\n    Where to get it: Download them from your bank's website or app.\n    What we need to see: Every page of each statement, including pages that say 'left blank'.\n\n- Pay stubs \u2014 your most recent 30 days\n    Where to get it: From your employer's payroll portal.\n    What we cannot accept: a screenshot of the portal instead of the stub itself.";

/** Substitute every `$placeholder` with something plausible, so only the SHAPE is under test. */
function filled(text: string): string {
  return text
    .replace(/\$document_list/g, DOCUMENT_LIST)
    .replace(/\$condition_list/g, DOCUMENT_LIST)
    .replace(/\$secure_upload_block/g, "Email is not a fully secure channel.")
    .replace(/\$[a-z_]+/g, "a value");
}

function templateBodies(): { name: string; body: string }[] {
  const names = readdirSync(TEMPLATES_DIR).filter((n) => n.endsWith(".txt"));
  expect(names.length).toBeGreaterThan(8);
  return names.map((name) => {
    const raw = readFileSync(`${TEMPLATES_DIR}${name}`, "utf8");
    const body = raw.startsWith("Subject:") ? raw.slice(raw.indexOf("\n") + 1) : raw;
    return { name, body: filled(body) };
  });
}

const OURS = new Set(["p", "br", "ul", "li", "strong"]);

describe("every registered template, rendered for the clipboard", () => {
  it("emits only the five tags this renderer owns, and no attributes", () => {
    for (const { name, body } of templateBodies()) {
      const html = emailBodyToHtml(body);
      const tags = [...html.matchAll(/<\/?([a-zA-Z][a-zA-Z0-9]*)\b[^>]*>/g)].map((m) =>
        (m[1] ?? "").toLowerCase(),
      );
      expect(
        tags.filter((t) => !OURS.has(t)),
        `${name} emitted a foreign tag`,
      ).toEqual([]);
      expect(
        [...html.matchAll(/<([a-zA-Z][a-zA-Z0-9]*)\s+[^>]*>/g)].map((m) => m[0]),
        `${name} emitted an attribute — the entity set is sufficient only because it does not`,
      ).toEqual([]);
    }
  });

  it("closes every list item and every list", () => {
    for (const { name, body } of templateBodies()) {
      const html = emailBodyToHtml(body);
      const opens = (html.match(/<li>/g) ?? []).length;
      const closes = (html.match(/<\/li>/g) ?? []).length;
      expect(closes, `${name} left ${opens - closes} <li> unclosed`).toBe(opens);
      expect((html.match(/<ul>/g) ?? []).length).toBe((html.match(/<\/ul>/g) ?? []).length);
    }
  });

  it("leaves no bold marker behind as literal text", () => {
    for (const { name, body } of templateBodies()) {
      expect(emailBodyToHtml(body), `${name} leaked a bold marker`).not.toContain("**");
    }
  });

  it("keeps the indented-detail rule honest in both directions", () => {
    // LP-844 REVIEW, the build's question C. The rule appends an indented line to the LAST BULLET, so
    // the same line means two different things depending on what precedes it. Asserted directly on the
    // renderer, because my first attempt at this asserted it through a template and could not fail:
    // removing the blank line after `$document_list` changed nothing, since the prose line between
    // them flushes the list anyway. A test that cannot fail from a plausible edit is not a guard.
    // LP-846 changed the SHAPE a fold produces — a nested list rather than `<br>` — and not the
    // rule. The property is still "this line belongs to that bullet".
    const folded = emailBodyToHtml("- a document\n    detail about it");
    expect(folded).toContain("<li>a document<ul><li>detail about it</li></ul></li>");

    const flushed = emailBodyToHtml("- a document\n\n    not a detail");
    expect(flushed).toContain("<li>a document</li>");
    expect(flushed).not.toContain("not a detail</li>");
    // LEADING WHITESPACE SURVIVES INTO THE PARAGRAPH. `line` strips trailing space only, so the
    // indent is still in the HTML — where it collapses, so it renders flush left while the
    // plain-text flavour of the same clipboard keeps it. Asserted as it is rather than as it reads:
    // the property under test is that the line is a paragraph and not a bullet's detail.
    expect(flushed).toContain("<p>    not a detail</p>");
  });

  it("puts no template's indented line where it would fold into the document list", () => {
    // And this is the template-shaped half, which CAN fail on an edit: an indented line immediately
    // after `$document_list`, with no blank and no prose between, folds into the last bullet. Today
    // `initial_documentation_request` has an indented `$inbox_address` — the address a borrower is
    // told to send documents to — separated from the list by both.
    for (const name of readdirSync(TEMPLATES_DIR).filter((n) => n.endsWith(".txt"))) {
      const lines = readFileSync(`${TEMPLATES_DIR}${name}`, "utf8").split("\n");
      for (const [i, line] of lines.entries()) {
        if (!line.includes("$document_list")) continue;
        const next = lines[i + 1] ?? "";
        expect(
          /^\s+\S/.test(next),
          `${name} line ${i + 2} is indented directly after $document_list — it would be folded into the last bullet rather than read as its own line`,
        ).toBe(false);
      }
    }
  });
});

describe("the only way HTML reaches the DOM", () => {
  /**
   * Every `__html` expression in the tree, with its braces balanced.
   *
   * NOT `[^}]*`, which is what this used and which LP-853 broke by making the one sink a ternary:
   * the expression now contains a `}`, the regex stopped at it, and the scan matched NOTHING —
   * reporting zero offenders and zero sinks. It failed only because the count control below caught
   * it. A guard is only as wide as what it looks at, and a narrow one is indistinguishable from a
   * clean result.
   */
  /**
   * Comment lines removed, code lines untouched.
   *
   * WHOLE LINES ONLY. A stripper that cut from `//` to the end of ANY line drops real code when a
   * line ends in a trailing comment, and mangles a `//` inside a string literal — this project has
   * already shipped that bug once. A comment that occupies its own line cannot be either.
   */
  const withoutComments = (source: string): string =>
    source
      .replace(/\/\*[\s\S]*?\*\//g, "")
      .split("\n")
      .filter((line) => !line.trim().startsWith("//"))
      .join("\n");

  const sinksIn = (raw: string): string[] => {
    // LP-853 — COMMENTS COME OUT FIRST. The marker used to be `={{\s*__html:`, and the sink this
    // ticket wrote has seven lines of comment between the braces and the key, so the scan matched
    // nothing at all: zero offenders, zero sinks, and only the count control below noticed.
    const source = withoutComments(raw);
    const found: string[] = [];
    const marker = /dangerouslySetInnerHTML=\{\{\s*__html:/g;
    for (const match of source.matchAll(marker)) {
      let depth = 2; // the two braces the marker itself opened
      let i = match.index + match[0].length;
      const from = i;
      while (i < source.length && depth > 0) {
        if (source[i] === "{") depth += 1;
        else if (source[i] === "}") depth -= 1;
        i += 1;
      }
      found.push(source.slice(from, i - 2).trim());
    }
    return found;
  };

  /**
   * The expressions permitted to reach `__html`, normalised to one line.
   *
   * LP-853 — THERE ARE TWO SAFETY ARGUMENTS NOW, AND THIS LISTS BOTH.
   *
   *   • `emailBodyToHtml(...)` — safe by CONSTRUCTION. It escapes every character that could begin
   *     markup before it emits a tag, so there is no passthrough to leave open. This is the only
   *     argument that existed before LP-853, and it still covers every `plain` body.
   *   • the `body_format === "html"` ternary — safe because the SERVER rebuilt that string from an
   *     allowlist on the way in (`app/communications/sanitise.py`). The column cannot hold a tag
   *     that was not permitted, so the guarantee belongs to the row rather than to this renderer.
   *
   * WRITTEN OUT IN FULL rather than pattern-matched, because "the body came from a sanitised
   * column" is a claim about the backend that no regex over this file can check. Listing it forces
   * the next person adding a sink to say which of the two arguments theirs rests on.
   */
  const ALLOWED = new Set([
    "emailBodyToHtml(data.body)",
    'data.body_format === "html" ? data.body : emailBodyToHtml(data.body)',
  ]);

  it("feeds every dangerouslySetInnerHTML from a renderer or a sanitised column, and nothing else", () => {
    const offenders: string[] = [];
    let sinks = 0;
    const walk = (dir: string) => {
      for (const entry of readdirSync(dir, { withFileTypes: true })) {
        const full = `${dir}/${entry.name}`;
        if (entry.isDirectory()) {
          walk(full);
          continue;
        }
        if (!/\.tsx?$/.test(entry.name) || /\.test\.tsx?$/.test(entry.name)) continue;
        for (const raw of sinksIn(readFileSync(full, "utf8"))) {
          sinks += 1;
          // Line breaks are formatting; the expression is what matters.
          const expression = raw.replace(/,\s*$/, "").replace(/\s+/g, " ").trim();
          if (!ALLOWED.has(expression)) offenders.push(`${entry.name}: ${expression}`);
        }
      }
    };
    for (const root of ["components", "app", "lib"]) walk(`${process.cwd()}/${root}`);

    expect(offenders).toEqual([]);
    // THE CONTROL AGAINST A SCAN THAT READ NOTHING, and it has now earned its keep twice: it is
    // what caught the `[^}]*` matcher going blind when LP-853 made the sink a ternary. The count
    // tracks the real number rather than holding a stale one.
    expect(sinks, "the scan found no sink — it read nothing").toBeGreaterThanOrEqual(1);
  });

  it("would notice an unsanitised sink", () => {
    // PLANTING THE THING IT FORBIDS. Every assertion above is a not-in over a tree that happens to
    // be clean, so without this the matcher could be wrong in a second way and still read green.
    const planted = "<div dangerouslySetInnerHTML={{ __html: message.rawBodyFromSomewhere }} />";
    const [expression] = sinksIn(planted);
    expect(expression).toBe("message.rawBodyFromSomewhere");
    expect(ALLOWED.has(expression ?? "")).toBe(false);
  });

  it("reads a sink whose braces are separated from its key by a comment", () => {
    // THE EXACT SHAPE THAT WENT BLIND. Planted, because a matcher that cannot see this reports a
    // clean tree, and a clean tree is what it reported.
    const planted = [
      "<div dangerouslySetInnerHTML={{",
      "  // a comment explaining the safety argument",
      "  __html: emailBodyToHtml(data.body),",
      "}} />",
    ].join("\n");
    expect(sinksIn(planted)).toEqual(["emailBodyToHtml(data.body),"]);
  });

  it("reads a ternary sink whole, braces and all", () => {
    // The exact shape LP-853 introduced, which the previous matcher truncated at the first `}`.
    const planted = `<div dangerouslySetInnerHTML={{ __html: a === "x" ? { y: 1 } : emailBodyToHtml(b) }} />`;
    expect(sinksIn(planted)).toEqual(['a === "x" ? { y: 1 } : emailBodyToHtml(b)']);
  });
});
