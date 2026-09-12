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
    const folded = emailBodyToHtml("- a document\n    detail about it");
    expect(folded).toContain("<li>a document<br>detail about it</li>");

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
  it("feeds every dangerouslySetInnerHTML from emailBodyToHtml and nothing else", () => {
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
        for (const m of readFileSync(full, "utf8").matchAll(
          /dangerouslySetInnerHTML=\{\{\s*__html:\s*([^}]*)\}\}/g,
        )) {
          sinks += 1;
          if (!/^emailBodyToHtml\(/.test((m[1] ?? "").trim())) {
            offenders.push(`${entry.name}: ${(m[1] ?? "").trim()}`);
          }
        }
      }
    };
    for (const root of ["components", "app", "lib"]) walk(`${process.cwd()}/${root}`);

    expect(offenders).toEqual([]);
    expect(sinks, "the scan found no sink — it read nothing").toBeGreaterThanOrEqual(2);
  });
});
