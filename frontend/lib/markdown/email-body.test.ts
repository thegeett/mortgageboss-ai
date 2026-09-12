import { describe, expect, it } from "vitest";
import { emailBodyToHtml } from "./email-body";

/**
 * LP-844 — the clipboard IS the send path, so this function's output is what reaches a borrower.
 * Everything here is about that, not about rendering fidelity on our own page.
 */
describe("emailBodyToHtml", () => {
  it("makes the document list a real list", () => {
    const html = emailBodyToHtml("Hello,\n\n- Bank statements\n- Pay stubs\n\nThank you");
    expect(html).toContain("<ul>");
    expect(html).toContain("<li>Bank statements</li>");
    expect(html).toContain("<li>Pay stubs</li>");
    expect(html).toContain("<p>Hello,</p>");
  });

  it("keeps a document's detail with its document, and readable", () => {
    // The catalog indents "Where to get it" under each item. A general markdown reader treats four
    // spaces as a CODE BLOCK, which would render the instructions in a monospace box detached from
    // the thing they describe.
    //
    // LP-846 — AND NOT AS A RUN-ON. LP-844 joined these with `<br>` inside the bullet, which the
    // user reported as the section being absent: three labelled facts became one sentence with no
    // indent and no emphasis, where the monospace block it replaced had them on separate lines.
    const html = emailBodyToHtml(
      "- Bank statements\n    Where to get it: your bank's portal\n    What we need to see: every page",
    );
    // A NESTED LIST, because the clipboard's HTML carries no classes and a mail client discards our
    // stylesheet — indentation has to come from a tag a composer keeps.
    expect(html).toContain("<li>Bank statements<ul>");
    expect(html).toContain("<li><strong>Where to get it:</strong> your bank&#39;s portal</li>");
    expect(html).toContain("<li><strong>What we need to see:</strong> every page</li>");
    expect(html).not.toContain("<br>");
    expect(html).not.toContain("<code>");
    expect(html).not.toContain("<pre>");
  });

  it("keeps consecutive documents in ONE list", () => {
    // LP-846 — the other half of the report. A blank line separates documents in the catalog's
    // output, and flushing the list on it made each document its own single-item `<ul>`: two
    // documents rendered as two lists with a gap, which is why the email read as a series of
    // fragments rather than a list of what is needed.
    const html = emailBodyToHtml("- Pay stubs\n\n- Bank statements");
    expect(html.match(/<ul>/g)).toHaveLength(1);
    expect(html).toContain("<li>Pay stubs</li><li>Bank statements</li>");
  });

  it("does not invent a label out of ordinary prose", () => {
    // The label rule matches `Word words:` at the start of a detail line. A sentence that merely
    // contains a colon must not be split at it — "Send it by Friday: the underwriter needs it"
    // would put half the sentence in bold.
    const html = emailBodyToHtml("- A document\n    send it by Friday because we need it");
    expect(html).toContain("<li>send it by Friday because we need it</li>");
    expect(html).not.toContain("<strong>");
  });

  it("emphasises what the template marked", () => {
    expect(emailBodyToHtml("Send the **most recent** statement")).toContain(
      "<strong>most recent</strong>",
    );
  });

  it("keeps a single newline as a line break, not a new paragraph", () => {
    const html = emailBodyToHtml("Borrower: Felicia Vance\nProperty: 41 Bellweather Lane");
    expect(html).toBe("<p>Borrower: Felicia Vance<br>Property: 41 Bellweather Lane</p>");
  });

  describe("what a body can contain, because a person wrote it", () => {
    it("renders a script tag as the text it is", () => {
      // A processor's note, a borrower's name and a rule's sentence all reach this function. The
      // output goes on the CLIPBOARD and then into a mail client — an output surface, not a preview.
      const html = emailBodyToHtml("Please send <script>alert(1)</script> the statement");
      expect(html).not.toContain("<script>");
      expect(html).toContain("&lt;script&gt;");
    });

    it("does not let an attribute escape into a tag", () => {
      // THE CASE ESCAPING `<` ALONE WOULD MISS if any tag were ever built from body text: a quote
      // that closes an attribute. Asserted because the escaping order is the entire security
      // argument here, and an author adding a tag later needs this to already be true.
      const html = emailBodyToHtml('Send it " onerror="alert(1)');
      expect(html).not.toContain('onerror="alert');
      expect(html).toContain("&quot;");
    });

    it("leaves a dollar amount alone", () => {
      // Bodies carry unresolved `$borrower_first_name` and real money. Neither is markup.
      const html = emailBodyToHtml("Proof of the $10,000 deposit\n\n$processor_name");
      expect(html).toContain("$10,000");
      expect(html).toContain("$processor_name");
    });

    it("does not invent emphasis from a lone asterisk", () => {
      expect(emailBodyToHtml("A * B")).toBe("<p>A * B</p>");
    });
  });
});

/**
 * LP-846 REVIEW — THE CASE ANALYSIS, DONE BY ENUMERATION RATHER THAN BY ARGUMENT.
 *
 * The blank-line rule now has three interacting conditions: a line is a bullet's detail if it is
 * indented, AND a bullet is open, AND no blank line has intervened. The ticket says three is where
 * its author stopped trusting their own reasoning about it, which is the right instinct — re-reading
 * the conditions cannot catch an error the reasoning produced.
 *
 * So every sequence of five lines over {bullet, indented, paragraph, blank} is rendered — 1024 of
 * them — and checked for the two properties that do not depend on knowing the intended output:
 * nothing is lost, and the tags balance with no paragraph opening inside a list. The specific
 * renderings that matter (a document's details nest, the inbox address does not get adopted) are
 * asserted by name in the tests above; this covers the combinations nobody thought to name.
 *
 * IT FAILS WHEN IT SHOULD: with the trailing `flushList()` removed, 453 of the 1024 report loss.
 */
const KINDS = {
  B: (i: number) => `- bullet${i}`,
  I: (i: number) => `    Where to get it: detail${i}`,
  P: (i: number) => `paragraph${i}`,
  _: () => "",
} as const;

type Kind = keyof typeof KINDS;

function sequencesOfFive(): Kind[][] {
  const keys = Object.keys(KINDS) as Kind[];
  let seqs: Kind[][] = [[]];
  for (let len = 0; len < 5; len++) {
    seqs = seqs.flatMap((s) => keys.map((k) => [...s, k]));
  }
  return seqs;
}

describe("every combination of line kinds", () => {
  it("loses no content and closes every tag", () => {
    const broken: string[] = [];
    for (const seq of sequencesOfFive()) {
      const html = emailBodyToHtml(seq.map((k, i) => KINDS[k](i)).join("\n"));
      const problems: string[] = [];
      const count = (re: RegExp) => (html.match(re) ?? []).length;
      if (count(/<li>/g) !== count(/<\/li>/g)) problems.push("unbalanced-li");
      if (count(/<ul>/g) !== count(/<\/ul>/g)) problems.push("unbalanced-ul");
      if (count(/<p>/g) !== count(/<\/p>/g)) problems.push("unbalanced-p");
      // A list item is not a place a paragraph can start. This is what `<br>`-joining used to do.
      if (/<ul>(?:(?!<\/ul>)[\s\S])*<p>/.test(html)) problems.push("p-inside-ul");
      for (const [i, k] of seq.entries()) {
        if (k === "_") continue;
        const token = k === "B" ? `bullet${i}` : k === "I" ? `detail${i}` : `paragraph${i}`;
        if (!html.includes(token)) problems.push(`lost:${k}${i}`);
      }
      if (problems.length > 0) broken.push(`${seq.join("")} -> ${problems.join(",")}`);
    }
    expect(broken).toEqual([]);
  });
});
