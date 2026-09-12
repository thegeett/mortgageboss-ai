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

  it("keeps a document's detail with its document", () => {
    // The catalog indents "Where to get it" under each item. A general markdown reader treats four
    // spaces as a CODE BLOCK, which would render the instructions in a monospace box detached from
    // the thing they describe.
    const html = emailBodyToHtml("- Bank statements\n    Where to get it: your bank's portal");
    expect(html).toContain("<li>Bank statements<br>Where to get it: your bank&#39;s portal</li>");
    expect(html).not.toContain("<code>");
    expect(html).not.toContain("<pre>");
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
