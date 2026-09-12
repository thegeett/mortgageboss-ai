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
