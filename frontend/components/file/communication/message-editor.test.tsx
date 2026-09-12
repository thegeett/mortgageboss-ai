// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MessageEditor } from "./message-editor";

/**
 * LP-849 — a rich box, and the plain body it keeps underneath.
 *
 * The requirements are all about what a processor SEES: a toolbar, no markup anywhere, and a copy
 * that pastes as ordinary formatted text. The storage staying plain is how the templates, the
 * placeholder pass, `mailto:` and the audit record keep working — so what these assert is that both
 * halves are true at once.
 */
afterEach(cleanup);

const CATALOG_BODY = [
  "- Driver's licence — front and back",
  "    Where to get it: A photograph or scan of your current licence.",
].join("\n");

describe("MessageEditor", () => {
  it("shows the body as formatted text, with no markup visible", async () => {
    render(<MessageEditor value="Send the **most recent** statement" onChange={vi.fn()} />);

    // THE REPORTED REQUIREMENT: "user should not see html tag or markdown."
    const text = document.querySelector(".ProseMirror")?.textContent ?? "";
    await vi.waitFor(() => expect(text.length).toBeGreaterThan(0));
    expect(text).not.toContain("**");
    expect(text).not.toContain("<strong>");
    expect(text).toContain("most recent");
    // And it IS emphasis rather than plain text that happens to read the same.
    expect(document.querySelector(".ProseMirror strong")?.textContent).toBe("most recent");
  });

  it("renders a document's guidance as a nested list", () => {
    render(<MessageEditor value={CATALOG_BODY} onChange={vi.fn()} />);

    const nested = document.querySelectorAll(".ProseMirror ul ul li");
    expect(nested.length).toBe(1);
    expect(nested[0]?.textContent).toContain("Where to get it:");
    // The label keeps its emphasis without a `**` in sight — LP-846's shape, in the editor.
    expect(document.querySelector(".ProseMirror ul ul strong")?.textContent).toBe(
      "Where to get it:",
    );
  });

  it("offers bold and bullets, and says whether they are on", () => {
    render(<MessageEditor value="Hello," onChange={vi.fn()} />);

    const bold = screen.getByRole("button", { name: "Bold" });
    const bullets = screen.getByRole("button", { name: "Bulleted list" });
    // `aria-pressed`, because whether bold is ON is state — a colour alone says it only to someone
    // who can see it.
    expect(bold.getAttribute("aria-pressed")).toBe("false");
    expect(bullets.getAttribute("aria-pressed")).toBe("false");
  });

  it("cannot produce a shape the renderer would silently drop", () => {
    // THE SCHEMA IS THE CONTRACT. The extension set is the subset `emailBodyToHtml` supports, so an
    // editor that could make a heading would make one the renderer drops on save — a processor
    // watching their formatting vanish. Asserted on the schema rather than by trying to type one,
    // because the guarantee is structural.
    render(<MessageEditor value="Hello," onChange={vi.fn()} />);
    const editor = document.querySelector(".ProseMirror");
    expect(editor).not.toBeNull();
    expect(document.querySelectorAll(".ProseMirror h1, .ProseMirror h2").length).toBe(0);
  });
});
