import { readFileSync, readdirSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { emailBodyToHtml } from "./email-body";
import { htmlToEmailBody } from "./from-html";

/**
 * LP-849 — stored text → HTML → the editor → HTML → stored text.
 *
 * The editor is a WYSIWYG and `Communication.body` stays one plain string, so EVERY KEYSTROKE
 * round-trips. A lossy inverse silently eats a processor's formatting, and the way it fails is
 * gradual: a body that survives one reopen and degrades on the fourth.
 *
 * So the property is tested as a FIXED POINT rather than case by case — `render(parse(render(x)))`
 * must equal `render(x)`. That catches drift no hand-written expectation would, because it does not
 * depend on my guessing which shapes matter.
 */
const CASES: [string, string][] = [
  ["a paragraph", "Hello Felicia,"],
  ["two paragraphs", "Hello,\n\nThank you"],
  ["a line break inside one", "Borrower: Felicia Vance\nProperty: 41 Bellweather Lane"],
  ["a flat list", "- Pay stubs\n- Bank statements"],
  [
    "the catalog's real shape",
    [
      "- Driver's licence — front and back",
      "    Where to get it: A photograph or scan of your current licence.",
      "    What we need to see: Both sides, unexpired.",
      "",
      "- Homeowner's insurance — the declarations page",
      "    Where to get it: From your insurance agent.",
    ].join("\n"),
  ],
  ["emphasis a processor typed", "Send the **most recent** statement"],
  ["a dollar amount and a placeholder", "Proof of the $10,000 deposit\n\n$processor_name"],
  ["an ampersand", "Smith & Sons payroll"],
  ["text that looks like a tag", "Please send <not-a-tag> it"],
  ["a quote", 'She said "send it today"'],
];

describe("the editor round trip", () => {
  for (const [name, body] of CASES) {
    it(`is a fixed point: ${name}`, () => {
      const once = emailBodyToHtml(body);
      const back = htmlToEmailBody(once);
      // The HTML is what the editor shows and what the clipboard carries, so THAT is what must not
      // drift. Comparing the text instead would fail on cosmetic whitespace the renderer ignores.
      expect(emailBodyToHtml(back)).toBe(once);
    });
  }

  it("does not inflate a catalog label into asterisks", () => {
    // THE ASYMMETRY. The renderer bolds "Where to get it:" itself; the processor did not type `**`
    // and must not find any on reopening. Getting this wrong adds `**` to every template body on
    // every edit — invisible in the editor and visible in the plain-text clipboard flavour and in
    // the mailto: body.
    const body = "- Bank statements\n    Where to get it: your bank's portal";
    const back = htmlToEmailBody(emailBodyToHtml(body));

    expect(back).toBe(body);
    expect(back).not.toContain("**");
  });

  it("keeps emphasis a processor really did type", () => {
    // The control for the rule above: same tag, different meaning, and the inverse has to tell them
    // apart. If `asLabel` suppressed every `<strong>`, this would silently lose the processor's own
    // formatting — a worse failure than the one it prevents, because they chose it.
    const back = htmlToEmailBody(emailBodyToHtml("Send the **March** statement"));
    expect(back).toBe("Send the **March** statement");
  });

  it("does not double-decode an entity the author typed", () => {
    // `escapeHtml` escapes `&` FIRST so `&lt;` survives as text; the inverse decodes it LAST for the
    // same reason. Reversed, a literal "&lt;" a processor typed comes back as "<".
    const back = htmlToEmailBody(emailBodyToHtml("Type &lt;name&gt; in the form"));
    expect(back).toBe("Type &lt;name&gt; in the form");
  });
});

// --------------------------------------------------------------------------------------------- #
// LP-849 REVIEW — the two sweeps, because thirteen chosen shapes are thirteen shapes somebody
// thought of. A fixed point is a property, so it can be checked over a generated space.
// --------------------------------------------------------------------------------------------- #

const KINDS = {
  B: (i: number) => `- bullet${i}`,
  I: (i: number) => `    Where to get it: detail${i}`,
  P: (i: number) => `paragraph${i}`,
  _: () => "",
} as const;

type Kind = keyof typeof KINDS;

function everySequenceOfFive(): Kind[][] {
  const keys = Object.keys(KINDS) as Kind[];
  let seqs: Kind[][] = [[]];
  for (let i = 0; i < 5; i++) seqs = seqs.flatMap((s) => keys.map((k) => [...s, k]));
  return seqs;
}

const TEMPLATES_DIR = `${process.cwd()}/../backend/app/communications/templates/`;
const SUBSTITUTED_DOCUMENT_LIST = [
  "- Bank statement",
  "    Where to get it: your bank's website",
  "    Which months: the last two",
  "",
  "- W-2",
  "    Where to get it: your employer",
].join("\n");

describe("the round trip as a property", () => {
  it("is a fixed point for all 1024 sequences of five line kinds", () => {
    const diverged: string[] = [];
    for (const seq of everySequenceOfFive()) {
      const body = seq.map((k, i) => KINDS[k](i)).join("\n");
      const once = emailBodyToHtml(body);
      const twice = emailBodyToHtml(htmlToEmailBody(once));
      if (once !== twice) diverged.push(`${seq.join("")}: ${once} -> ${twice}`);
    }
    expect(diverged).toEqual([]);
  });

  it("is a fixed point for every real template", () => {
    const diverged: string[] = [];
    for (const name of readdirSync(TEMPLATES_DIR).filter((n) => n.endsWith(".txt"))) {
      const body = readFileSync(`${TEMPLATES_DIR}${name}`, "utf8")
        .replace(/\$document_list/g, SUBSTITUTED_DOCUMENT_LIST)
        .replace(/\$inbox_address/g, "lf-abc123@inbox.example.com");
      const once = emailBodyToHtml(body);
      if (once !== emailBodyToHtml(htmlToEmailBody(once))) diverged.push(name);
    }
    expect(diverged).toEqual([]);
  });
});

/**
 * HTML THE EDITOR CAN PRODUCE THAT THE RENDERER NEVER WOULD.
 *
 * The sweep above starts from a stored body, so it only ever feeds `htmlToEmailBody` the renderer's
 * own output — which cannot contain a second nesting level, because the plain form has no way to say
 * one. The schema CAN: `ListItem` admits a `BulletList`, which is what makes the catalog's guidance
 * expressible in the first place, and there is no depth limit on it.
 *
 * So these start from the HTML instead. The property is convergence rather than equality — the first
 * pass is allowed to normalise something into our subset, and every pass after it must agree.
 *
 * This is what found the review's one defect: two levels of nesting serialised `detail` and `deeper`
 * as `detaildeeper`, one word, no separator.
 */
const EDITOR_SHAPES: [string, string][] = [
  ["list item content wrapped in a paragraph", "<ul><li><p>one</p></li><li><p>two</p></li></ul>"],
  [
    "a second nesting level",
    "<ul><li><p>doc</p><ul><li><p>detail</p><ul><li><p>deeper</p></li></ul></li></ul></li></ul>",
  ],
  [
    "a third",
    "<ul><li><p>a</p><ul><li><p>b</p><ul><li><p>c</p><ul><li><p>d</p></li></ul></li></ul></li></ul></li></ul>",
  ],
  ["two lists with nothing between them", "<ul><li><p>a</p></li></ul><ul><li><p>b</p></li></ul>"],
  [
    "a paragraph between two lists",
    "<ul><li><p>a</p></li></ul><p>mid</p><ul><li><p>b</p></li></ul>",
  ],
  [
    "bold ending in a colon inside a detail",
    "<ul><li><p>doc</p><ul><li><p><strong>Note:</strong> careful</p></li></ul></li></ul>",
  ],
  [
    "bold not ending in a colon inside a detail",
    "<ul><li><p>doc</p><ul><li><p><strong>careful</strong> now</p></li></ul></li></ul>",
  ],
  [
    "two bolds in one detail",
    "<ul><li><p>doc</p><ul><li><p><strong>Where:</strong> bank <strong>When:</strong> soon</p></li></ul></li></ul>",
  ],
  ["a hard break in a paragraph", "<p>line one<br>line two</p>"],
  ["a hard break inside a list item", "<ul><li><p>a<br>b</p></li></ul>"],
  ["bold across a whole paragraph", "<p><strong>all of it</strong></p>"],
  ["an empty paragraph between two", "<p>a</p><p></p><p>b</p>"],
  ["a list item with no paragraph wrapper", "<ul><li>plain</li></ul>"],
];

describe("html the editor can produce", () => {
  for (const [name, html] of EDITOR_SHAPES) {
    it(`converges and loses no words: ${name}`, () => {
      const body = htmlToEmailBody(html);
      const once = emailBodyToHtml(body);
      // Converged: normalising again changes nothing.
      expect(emailBodyToHtml(htmlToEmailBody(once))).toBe(once);
      // AND EVERY WORD SURVIVED AS A WHOLE WORD, which is the half convergence does not cover:
      // collapsing everything to an empty string converges perfectly, and so does running two words
      // together. A substring check passes for `detaildeeper` — which is exactly the defect this
      // sweep was written to find — so compare TOKENS.
      const tokensOf = (text: string) =>
        (text.replace(/<[^>]+>/g, " ").match(/[A-Za-z]+/g) ?? []).filter((w) => w !== "br");
      const survived = tokensOf(once);
      for (const word of tokensOf(html)) expect(survived).toContain(word);
    });
  }

  it("keeps a deeper level's words apart instead of running them together", () => {
    // THE REVIEW'S DEFECT, named rather than left to the sweep. Reachable by pressing Tab twice, and
    // unavoidably by pasting a nested list out of another mail client.
    const body = htmlToEmailBody(
      "<ul><li><p>doc</p><ul><li><p>detail</p><ul><li><p>deeper</p></li></ul></li></ul></li></ul>",
    );
    expect(body).toBe("- doc\n    detail\n    deeper");
    expect(body).not.toContain("detaildeeper");
  });
});

/**
 * THE LABEL RULE IS ONE RULE IN BOTH DIRECTIONS (LP-849 review).
 *
 * The ticket calls the label/emphasis split the load-bearing judgement and says a processor who types
 * bold ending in a colon loses their asterisks, which it judged acceptable. That is true of a
 * capitalised label the renderer re-emphasises — `**Note:**` stores as `Note:` and comes back bold, so
 * nothing a processor can see has changed.
 *
 * It was NOT true of the five cases where the two rules disagreed. `htmlToEmailBody` stripped the
 * asterisks from any `<strong>` ending in a colon; `emailBodyToHtml` re-bolds only a capitalised run of
 * three to forty-one characters. So a lowercase label, a very short one, a very long one, or one
 * starting with a digit lost its asterisks on the way to storage and was not bolded on the way back —
 * the formatting silently gone for good, which is the failure the schema restriction exists to prevent.
 */
const BOLD_IN_A_DETAIL = [
  ["a capitalised label the renderer emphasises", "Note:", false],
  ["lowercase", "note:", true],
  ["one character before the colon", "A:", true],
  ["two characters before the colon", "Ab:", true],
  ["longer than the renderer's label rule allows", `A${"x".repeat(45)}:`, true],
  ["starting with a digit", "2 things:", true],
  ["already containing a colon", "Note: really:", true],
] as const;

describe("bold that ends in a colon inside a detail line", () => {
  for (const [name, text, keepsAsterisks] of BOLD_IN_A_DETAIL) {
    it(`survives the round trip: ${name}`, () => {
      const html = `<ul><li><p>doc</p><ul><li><p><strong>${text}</strong> careful</p></li></ul></li></ul>`;
      const body = htmlToEmailBody(html);
      // Whether the stored form keeps the markers is a detail of which rule applied...
      expect(body.includes(`**${text}**`)).toBe(keepsAsterisks);
      // ...but the processor must see their bold either way, which is the part that matters.
      expect(emailBodyToHtml(body)).toContain(`<strong>${text}</strong>`);
    });
  }

  it("still does not inflate a real catalog label", () => {
    // The other direction, and the reason the rule is not simply "always keep the asterisks": the
    // templates emit these by the dozen, and `**Where to get it:**` in a stored body would be wrong
    // in the plain-text mail and would grow on every reopen.
    const rendered = emailBodyToHtml("- Bank statement\n    Where to get it: your bank");
    expect(htmlToEmailBody(rendered)).toBe("- Bank statement\n    Where to get it: your bank");
  });
});
