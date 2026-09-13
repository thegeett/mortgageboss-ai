/**
 * LP-854 — the three lists that must name the same tags, checked against ONE of them.
 *
 * The ticket's requirement is *"derive the list once and import it into all three places. Not three
 * copies that agree today."* Two of the three are TypeScript and can genuinely import; the third is
 * Python and cannot. So this file is the import the language boundary will not allow: it reads
 * `sanitise.py`'s `ALLOWED` out of the source and fails when it and `EMAIL_SCHEMA` disagree.
 *
 * THE TEST THAT MATTERS IS THE ONE AT THE BOTTOM. Everything above passes on three hand-edited
 * copies that happen to agree on the day they were written — which is exactly what the ticket says
 * not to build. `adding a tag to one list alone fails` plants the drift and shows the check catches
 * it, in both directions.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { EXTENSIONS } from "@/components/file/communication/message-editor";
import { describe, expect, it } from "vitest";
import { emailBodyToHtml } from "./email-body";
import { ALLOWED_SCHEMES, AT_RISK_IN_WORD, EMAIL_SCHEMA, EMAIL_TAGS } from "./schema";

const SANITISER = join(process.cwd(), "..", "backend", "app", "communications", "sanitise.py");

/** `ALLOWED` from `sanitise.py`, as `{tag: [attribute, ...]}`. */
function serverAllowlist(source: string): Record<string, string[]> {
  const block = /ALLOWED: dict\[str, frozenset\[str\]\] = \{([\s\S]*?)\n\}/.exec(source);
  if (!block) throw new Error("ALLOWED not found in sanitise.py — this scan read nothing");
  const found: Record<string, string[]> = {};
  for (const line of (block[1] ?? "").split("\n")) {
    // `[a-z0-9]`, NOT `[a-z]`. The first version excluded digits, so a planted `h1` was invisible
    // to the parser and the drift check passed over a list containing a heading — the exact tag an
    // allowlist most needs to notice. Found by the planted case below rather than by reading.
    const entry = /^\s*"([a-z0-9]+)":\s*frozenset\(([\s\S]*)\),\s*$/.exec(line);
    if (!entry) continue;
    const attributes = [...(entry[2] ?? "").matchAll(/"([a-z-]+)"/g)].map((m) => m[1] ?? "");
    found[entry[1] ?? ""] = attributes;
  }
  return found;
}

/** The schemes `sanitise.py` permits on an href. */
function serverSchemes(source: string): string[] {
  const block = /ALLOWED_SCHEMES = frozenset\(\{([^}]*)\}\)/.exec(source);
  if (!block) throw new Error("ALLOWED_SCHEMES not found — this scan read nothing");
  return [...(block[1] ?? "").matchAll(/"([a-z]+)"/g)].map((m) => m[1] ?? "").sort();
}

const SOURCE = readFileSync(SANITISER, "utf8");

describe("the reader can actually read", () => {
  it("finds a real allowlist, not an empty one", () => {
    // THE POSITIVE CONTROL FOR THE PARSER. Every comparison below is satisfied by two empty sets,
    // and a regex that stopped matching after a reformat would produce exactly that — a green
    // drift check over a list it never read.
    const allowed = serverAllowlist(SOURCE);
    expect(Object.keys(allowed).length).toBeGreaterThanOrEqual(10);
    expect(allowed.p).toEqual([]);
    expect(allowed.a).toEqual(["href"]);
    expect(serverSchemes(SOURCE)).toEqual(["http", "https", "mailto"]);
  });
});

describe("the three lists agree", () => {
  it("the server allowlist is exactly the schema", () => {
    expect(Object.keys(serverAllowlist(SOURCE)).sort()).toEqual([...EMAIL_TAGS].sort());
  });

  it("and so are its attributes", () => {
    const allowed = serverAllowlist(SOURCE);
    for (const [tag, attributes] of Object.entries(EMAIL_SCHEMA)) {
      expect(allowed[tag], `attributes for <${tag}>`).toEqual([...attributes]);
    }
  });

  it("the link schemes agree", () => {
    expect(serverSchemes(SOURCE)).toEqual([...ALLOWED_SCHEMES].sort());
  });

  it("every enabled Tiptap extension is in the schema, and vice versa", () => {
    // The extensions are objects, so the comparison is on the TAG each produces — which is the
    // thing that has to match, and which `EMAIL_SCHEMA`'s keys are.
    //
    // Structural extensions emit nothing and are excluded by name: `doc` and `text` are the
    // document itself, and `undoRedo` is a history stack.
    const structural = new Set(["doc", "text", "undoRedo"]);
    const produced = new Set(
      EXTENSIONS.map((extension) => TAG_OF[extension.name] ?? extension.name).filter(
        (name) => !structural.has(name),
      ),
    );
    expect([...produced].sort()).toEqual([...EMAIL_TAGS].sort());
  });

  it("everything the plain renderer emits is allowed", () => {
    // A SUBSET, not an equality, and the asymmetry is the point: the plain body format has no
    // syntax for underline, links, ordered lists or quotes, so `emailBodyToHtml` cannot emit them
    // and is not expected to. What must hold is that everything it DOES emit survives the
    // sanitiser, or a generated draft would be mangled the first time anything sanitised it.
    const corpus = [
      "Hello,\n\nPlease send the **most recent** statement.",
      "- Bank statement\n    Where to get it: your bank\n- Pay stub",
      "Acme Mortgage\n123 Main Street",
      "5 < 6 & 7 > 2",
    ];
    const emitted = new Set<string>();
    for (const body of corpus) {
      for (const match of emailBodyToHtml(body).matchAll(/<\/?([a-z]+)/g)) {
        emitted.add(match[1] ?? "");
      }
    }
    expect(emitted.size).toBeGreaterThan(0);
    for (const tag of emitted) {
      expect(EMAIL_TAGS, `<${tag}> is emitted by the renderer`).toContain(tag);
    }
  });
});

/** Tiptap's extension name -> the tag it produces, where the two differ. */
const TAG_OF: Record<string, string> = {
  paragraph: "p",
  hardBreak: "br",
  bold: "strong",
  italic: "em",
  underline: "u",
  bulletList: "ul",
  orderedList: "ol",
  listItem: "li",
  blockquote: "blockquote",
  link: "a",
};

describe("the check can fail", () => {
  it("adding a tag to one list alone fails, in both directions", () => {
    // THE TEST THAT MAKES THE REST MEAN ANYTHING. Everything above is satisfied by three hand-edited
    // copies that happen to agree today, which is precisely what the ticket forbids. This plants the
    // drift the ticket is about — a mark added on one side and not the other — and shows the
    // comparison catches it, so "derive once" is enforced rather than asserted.
    const withExtra = SOURCE.replace(
      '    "a": frozenset({"href"}),',
      '    "a": frozenset({"href"}),\n    "h1": frozenset(),',
    );
    expect(withExtra).not.toBe(SOURCE);
    expect(Object.keys(serverAllowlist(withExtra)).sort()).not.toEqual([...EMAIL_TAGS].sort());

    // And the other way: a tag in the schema that the server does not allow.
    const withMissing = SOURCE.replace('    "blockquote": frozenset(),\n', "");
    expect(withMissing).not.toBe(SOURCE);
    expect(Object.keys(serverAllowlist(withMissing)).sort()).not.toEqual([...EMAIL_TAGS].sort());
  });

  it("an attribute added on one side alone fails", () => {
    const withExtra = SOURCE.replace('    "p": frozenset(),', '    "p": frozenset({"style"}),');
    expect(withExtra).not.toBe(SOURCE);
    expect(serverAllowlist(withExtra).p).not.toEqual([...(EMAIL_SCHEMA.p ?? [])]);
  });

  it("every tag flagged as at risk in Word is a tag we actually emit", () => {
    // LP-854 REVIEW — `AT_RISK_IN_WORD` sits beside the canonical list and is NOT derived from it,
    // which I found by mutating the wrong one: renaming it there changed nothing, because no test
    // reads it. That is fine for what it is — guidance, not a schema — right up until the schema
    // moves without it. It names what the person doing the manual Gmail and Outlook paste should
    // look at, so a stale entry sends them hunting for a tag the renderer can no longer produce,
    // and a tag dropped from it is one they will not think to check.
    //
    // Only one direction is a rule: every at-risk tag must be one we emit. The reverse is not,
    // because `p`, `br`, `strong` and `em` are deliberately excluded — every engine keeps them.
    for (const tag of AT_RISK_IN_WORD) {
      expect(EMAIL_TAGS).toContain(tag);
    }
    expect(AT_RISK_IN_WORD.length).toBeGreaterThan(0);
  });
});
