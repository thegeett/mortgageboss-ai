/**
 * Every text-bearing form control stays at 16px on mobile.
 *
 * Mobile Safari zooms the viewport whenever a focused control computes under
 * 16px and does not zoom back out. SPEC's amendment states the rule — "form
 * controls stay at 16px on mobile: `text-field md:text-…`, never a bare size" —
 * and it has now been broken three separate ways: the density retune dropped the
 * guard from Input and Textarea, Select was missed when they were fixed, and
 * EditableRow re-broke both by passing `text-sm` down as a className, which
 * tailwind-merge resolves as the winning font-size.
 *
 * A source scan rather than a render: the failure is a class string, it spans
 * primitives and raw elements in feature code alike, and the thing that must not
 * happen is a NEW control appearing without the guard.
 */
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * A font-size class with no variant prefix. `md:text-sm` and `file:text-sm` are
 * fine — they cannot apply at the widths where Safari zooms.
 */
const BARE_SIZE = /(?<![\w:-])text-(xs|sm|base|lg|xl|2xl|3xl)\b/g;

/** Every .tsx under app/ and components/. */
function sourceFiles(): string[] {
  const root = new URL("../../", import.meta.url).pathname;
  const walk = (dir: string): string[] =>
    readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
      const full = join(dir, e.name);
      if (e.isDirectory()) return walk(full);
      return e.name.endsWith(".tsx") && !e.name.endsWith(".test.tsx") ? [full] : [];
    });
  return [...walk(join(root, "app")), ...walk(join(root, "components"))];
}

function read(path: string): string {
  return readFileSync(new URL(`../../${path}`, import.meta.url), "utf8");
}

/**
 * The `className` each `<Input>` / `<Select>` / `<Textarea>` element is given by
 * its caller, across the whole tree. `cn` puts the caller's string last and
 * tailwind-merge treats every font size as one group, so a size here beats the
 * primitive's own — which is how EditableRow silently re-broke the guard.
 */
function callerClassNames(source: string): { element: string; classes: string }[] {
  const out: { element: string; classes: string }[] = [];
  for (const match of source.matchAll(/<(Input|Select|Textarea)\b/g)) {
    // Slice to the NEXT JSX tag rather than to the next ">": an attribute like
    // `onChange={(e) => …}` contains a ">", so an attribute-terminated regex
    // captures nothing and the check silently passes. Arrow bodies here contain
    // no "<", so the next "<" is reliably the end of this element's attributes.
    const from = (match.index ?? 0) + match[0].length;
    const next = source.indexOf("<", from);
    const attrs = source.slice(from, next === -1 ? source.length : next);
    const found = /className=\{?"([^"]*)"/.exec(attrs);
    if (found?.[1]) out.push({ element: match[1] ?? "", classes: found[1] });
  }
  return out;
}

// Files holding a text-bearing form control, primitive or raw. A file lands here
// when it gains one; the assertions below then hold it to the rule.
const CONTROLS = [
  "components/ui/input.tsx",
  "components/ui/textarea.tsx",
  "components/ui/select.tsx",
  "components/file/documents/document-drawer.tsx",
  "components/file/verification/rule-finding-actions.tsx",
  "app/(protected)/admin/validation/page.tsx",
  "app/(protected)/dev/extraction-bench/page.tsx",
];

describe("form controls do not trigger iOS auto-zoom", () => {
  it.each(CONTROLS)("%s sets text-field on its control", (path) => {
    expect(read(path)).toContain("text-field");
  });

  it.each(["components/ui/input.tsx", "components/ui/textarea.tsx", "components/ui/select.tsx"])(
    "%s carries no unprefixed font size",
    (path) => {
      // The primitives are the control and nothing else, so the whole file is
      // fair game — no label or helper text to produce a false positive.
      expect([...read(path).matchAll(BARE_SIZE)].map((m) => m[0])).toEqual([]);
    },
  );

  it("no caller overrides a primitive's size from the outside", () => {
    // The generalised form of the EditableRow bug: `className="h-8 text-sm"` on
    // <Input> won over the primitive's `text-field md:text-sm`. A caller's
    // className is for geometry; the size belongs to the control.
    const offenders: string[] = [];
    for (const file of sourceFiles()) {
      for (const { element, classes } of callerClassNames(readFileSync(file, "utf8"))) {
        if (BARE_SIZE.test(classes)) offenders.push(`<${element} className="${classes}">`);
        BARE_SIZE.lastIndex = 0;
      }
    }
    expect(offenders).toEqual([]);
  });
});
