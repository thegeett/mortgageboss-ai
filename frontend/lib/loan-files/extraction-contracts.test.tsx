import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
// @vitest-environment jsdom
/**
 * Every list-valued key the extraction contracts declare, rendered (LP-702).
 *
 * The bug was reported on two documents. It was in seventy-eight keys across
 * sixty-seven document types, because the display layer stringified any value
 * that was not a scalar and only two key names had been special-cased. Testing
 * the two reported keys would have left the other seventy-six.
 *
 * So this reads the CONTRACTS THEMSELVES — the JSON shape at the end of each
 * `app/ai/prompts/extraction/*.txt`, which is what the model is told to return
 * — and renders one document of every type. A contract that grows a new list
 * key is covered the day it is written, with nothing to remember.
 *
 * It asserts on RENDERED TEXT, not on the helper's return value: the helper
 * could be right and a component could still hand an object to React.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ExtractionView } from "@/components/file/documents/extraction-view";

const PROMPT_DIR = join(process.cwd(), "..", "backend", "app", "ai", "prompts", "extraction");

/** The stringification this whole ticket exists to make impossible. */
const STRINGIFIED = "[object Object]";

interface ListShape {
  /** The document type, from the prompt's filename. */
  type: string;
  /** The list-valued key, e.g. `payment_ledger`. */
  key: string;
  /** The keys each row of that list carries. Empty when the contract declares plain values. */
  rowKeys: string[];
}

/**
 * The list keys in one extraction contract.
 *
 * Read with a regex rather than a JSON parse: the contracts are a TEMPLATE
 * (`{"value": <string|null>, ...}`), not JSON, and several carry prose and
 * unbalanced braces around them. The regex asks the narrow question — which
 * top-level keys are declared as arrays, and what do their rows contain — which
 * is answerable without the file being valid anything.
 */
function listShapes(type: string, text: string): ListShape[] {
  const marker = /Respond with ONLY[^\n]*\n/.exec(text);
  const region = text.slice(marker ? marker.index + marker[0].length : 0);
  const shapes: ListShape[] = [];
  for (const match of region.matchAll(/^ {2}"(\w+)":\s*\[/gm)) {
    const from = match.index + match[0].length - 1;
    let depth = 0;
    let end = region.length;
    for (let i = from; i < region.length; i++) {
      const ch = region[i];
      if (ch === "[") depth += 1;
      else if (ch === "]") {
        depth -= 1;
        if (depth === 0) {
          end = i;
          break;
        }
      }
    }
    const body = region.slice(from, end);
    const rowKeys: string[] = [];
    for (const key of body.matchAll(/"(\w+)"\s*:/g)) {
      const name = key[1];
      if (name && !rowKeys.includes(name)) rowKeys.push(name);
    }
    shapes.push({ type, key: match[1] as string, rowKeys });
  }
  return shapes;
}

const CONTRACTS: ListShape[] = readdirSync(PROMPT_DIR)
  .filter((name) => name.endsWith(".txt"))
  .flatMap((name) =>
    listShapes(name.replace(/\.txt$/, ""), readFileSync(join(PROMPT_DIR, name), "utf8")),
  )
  // The catch-all has its own labelled renderer and its own shape; it is not one
  // of the list fields this ticket is about.
  .filter((shape) => shape.key !== "additional_sections");

/** A document of `type`, with every declared list key filled with two rows. */
function extractionFor(type: string): Record<string, unknown> {
  const data: Record<string, unknown> = {
    // A scalar alongside them, so a document is never all tables.
    document_type: { value: type, source: { page: 1, snippet: type } },
  };
  for (const shape of CONTRACTS.filter((s) => s.type === type)) {
    data[shape.key] =
      shape.rowKeys.length === 0
        ? ["a plain value", "another"]
        : [
            {
              ...Object.fromEntries(shape.rowKeys.map((k, i) => [k, `${k}-${i}`])),
              // A NESTED OBJECT ON EVERY ROW. Several contracts declare one
              // (`installments_and_due_dates` has `source`), and it is the shape
              // that produced the reported `[object Object]` — so every type
              // exercises it rather than the one that happens to declare it.
              source: { page: 2, snippet: `read from ${shape.key}` },
            },
            // A SECOND ROW MISSING A KEY. Columns read off row one would drop it.
            Object.fromEntries(shape.rowKeys.slice(1).map((k, i) => [k, `${k}-${i}`])),
          ];
  }
  return data;
}

const TYPES = [...new Set(CONTRACTS.map((s) => s.type))].sort();

describe("the extraction contracts themselves", () => {
  /**
   * The positive control.
   *
   * A parser that silently matched nothing would make every assertion below
   * pass over an empty list. These floors are under the counts measured on
   * 2026-09-06 (67 types, 78 keys) — they catch a parser that broke, not a
   * contract that changed.
   */
  it("finds the list keys it is meant to be testing", () => {
    expect(TYPES.length).toBeGreaterThanOrEqual(60);
    expect(CONTRACTS.length).toBeGreaterThanOrEqual(70);
  });

  it("includes the keys the bug was reported on", () => {
    const keys = CONTRACTS.map((s) => `${s.type}.${s.key}`);
    expect(keys).toContain("hoa_statement.payment_ledger");
    expect(keys).toContain("pay_stub.earnings_lines");
    expect(keys).toContain("pay_stub.deduction_lines");
    expect(keys).toContain("bank_statement.transactions");
  });
});

describe.each(TYPES)("%s", (type) => {
  it("renders no stringified object anywhere", () => {
    const { container, unmount } = render(<ExtractionView data={extractionFor(type)} />);
    expect(container.textContent ?? "").not.toContain(STRINGIFIED);
    unmount();
  });

  it("shows each list's rows rather than a count alone", () => {
    const { container, unmount } = render(<ExtractionView data={extractionFor(type)} />);
    const text = container.textContent ?? "";
    for (const shape of CONTRACTS.filter((s) => s.type === type)) {
      // SOME cell, not the first one: a row key that names an identifier
      // (`account_number_masked`) is masked on the way out, so its probe value
      // is correctly absent from the page.
      const shown =
        shape.rowKeys.length === 0
          ? text.includes("a plain value")
          : shape.rowKeys.some((key, i) => text.includes(`${key}-${i}`));
      expect(shown, `${shape.key} rendered no rows`).toBe(true);
    }
    unmount();
  });
});

describe("a shape no contract declares", () => {
  it("still never stringifies — tolerance is the point, not a list of known keys", () => {
    render(
      <ExtractionView
        data={{
          // Three levels of nesting, which no contract asks for and a model can
          // still return.
          odd_field: [{ nested: { deeper: { deepest: [1, 2, 3] } } }],
          bare_object: { a: 1, b: { c: 2 } },
          mixed_list: ["a string", { an: "object" }, 7],
        }}
      />,
    );
    expect(document.body.textContent ?? "").not.toContain(STRINGIFIED);
    // And it is not blank either — refusing to stringify by rendering nothing
    // would pass the assertion above and lose the field.
    expect(screen.getByText(/Odd field/)).toBeTruthy();
  });
});
