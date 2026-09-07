import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import { COLUMNS, columnClass } from "./file-table";

/**
 * The pipeline's column drop order is a decision, not an accident (LP-UI-037).
 *
 * All nine used to render at every width and simply got narrower, which is a
 * decision too — just one nobody made, and it degrades the columns a processor
 * triages on at the same rate as the ones they do not.
 *
 * Measured live: 1536 shows all nine, 1280 drops Touched, 1100 drops Property
 * and Lender, 900 drops Amount and Needs. These assertions are what stop that
 * order changing by someone adding a class.
 */
describe("column priority", () => {
  const byLabel = (label: string) => COLUMNS.find((c) => c.label === label);

  it("never drops the four a processor triages on", () => {
    // What it is, who it is, where it is in the process, and whether it needs
    // me. Without these the screen stops answering the question it exists for.
    for (const label of ["File", "Borrower", "Stage", "Attention"]) {
      expect(byLabel(label)?.hideBelow, `${label} must survive every width`).toBeNull();
    }
  });

  it("gives up Touched first — the default sort already encodes recency", () => {
    expect(byLabel("Touched")?.hideBelow).toBe("2xl");
  });

  it("gives up the identifying-but-redundant pair next", () => {
    // The borrower already identifies the file; the lender is rarely why one is
    // opened from this screen.
    expect(byLabel("Property")?.hideBelow).toBe("xl");
    expect(byLabel("Lender")?.hideBelow).toBe("xl");
  });

  it("keeps progress and size longest of the droppable ones", () => {
    expect(byLabel("Amount")?.hideBelow).toBe("lg");
    expect(byLabel("Needs")?.hideBelow).toBe("lg");
  });

  it("drops nothing below sm — this app does not claim a phone layout", () => {
    for (const column of COLUMNS) {
      expect(column.hideBelow).not.toBe("sm");
      expect(column.hideBelow).not.toBe("md");
    }
  });

  it("returns the right class string", () => {
    expect(columnClass("xl")).toBe("hidden xl:table-cell");
    expect(columnClass("lg")).toBe("hidden lg:table-cell");
    expect(columnClass("2xl")).toBe("hidden 2xl:table-cell");
    expect(columnClass(null)).toBe("");
  });

  it("spells each class out in the SOURCE, because Tailwind scans text", () => {
    /**
     * The assertion above cannot catch this. An interpolated
     * `hidden ${bp}:table-cell` returns exactly the right string at runtime and
     * passes it — while Tailwind, which reads the file rather than running it,
     * never emits the class, so every column renders at every width and the
     * whole suite stays green.
     *
     * The check therefore has to look where the failure lives: the source text.
     */
    const source = readFileSync(new URL("./file-table.tsx", import.meta.url), "utf8");
    for (const column of COLUMNS) {
      if (column.hideBelow === null) continue;
      expect(source, `Tailwind never sees hidden ${column.hideBelow}:table-cell`).toContain(
        `"hidden ${column.hideBelow}:table-cell"`,
      );
    }
  });

  it("has a class for every breakpoint the columns actually name", () => {
    // The gap this closes: adding `hideBelow: "md"` to a column without adding
    // its case falls through to "" and the column silently never hides.
    for (const column of COLUMNS) {
      if (column.hideBelow === null) continue;
      expect(columnClass(column.hideBelow), `no class for ${column.hideBelow}`).not.toBe("");
    }
  });
});
