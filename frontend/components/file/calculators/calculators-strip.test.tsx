// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

// Per-calculator, as the real hook is: one shared object would give all four
// tiles the same title and the assertions below would be ambiguous.
const titles = vi.hoisted(() => ({ value: {} as Record<string, string> }));
vi.mock("@/lib/api/calculators", () => ({
  useCalculator: (_fileId: string, calculator: string) => ({
    data: titles.value[calculator]
      ? { title: titles.value[calculator], headline: "Not required", status: "ok" }
      : undefined,
  }),
}));
vi.mock("@/lib/api/dti", () => ({ useDti: () => ({ data: undefined }) }));
vi.mock("@/lib/api/ltv", () => ({ useLtv: () => ({ data: undefined }) }));
vi.mock("@/components/file/dti/dti-calculator", () => ({ DtiCalculator: () => null }));
vi.mock("@/components/file/ltv/ltv-calculator", () => ({ LtvCalculator: () => null }));
vi.mock("@/components/file/calculators/calculator-card", () => ({ CalculatorCard: () => null }));

import { CalculatorsSection } from "./calculators-section";

afterEach(() => {
  cleanup();
  titles.value = {};
});

/**
 * The calculators are ONE STRIP (LP-UI-021, built in LP-UI-044).
 *
 * The ticket was named "calculator strip" and shipped as a 2/3-column grid, so
 * six calculators took two rows and pushed the outcome tabs — the point of the
 * verification screen — below the fold on a laptop. Reported from the app.
 */
describe("the calculator strip", () => {
  it("lays six tiles abreast where there is room", () => {
    const { container } = render(<CalculatorsSection fileId="f1" />);
    const strip = container.querySelector(".grid");
    expect(strip?.className).toContain("xl:grid-cols-6");
  });

  it("degrades by the LP-UI-037 ladder rather than wrapping arbitrarily", () => {
    // Three where a tile would otherwise be too narrow to read its own figure,
    // two at the bottom. A tile is a label over a number.
    const { container } = render(<CalculatorsSection fileId="f1" />);
    const strip = container.querySelector(".grid");
    expect(strip?.className).toContain("sm:grid-cols-3");
    expect(strip?.className).toContain("grid-cols-2");
  });

  it("uses the short labels, because six abreast truncates the long ones", () => {
    render(<CalculatorsSection fileId="f1" />);
    expect(screen.getByText("Mortgage ins.")).toBeTruthy();
    expect(screen.getByText("Self-employed")).toBeTruthy();
    expect(screen.getByText("Max loan")).toBeTruthy();
  });

  it("keeps the unabbreviated name as the accessible name", () => {
    // The label is short because the tile is ~9rem, not because the full name
    // stopped mattering — a screen reader still gets it.
    titles.value = { mortgage_insurance: "Mortgage insurance" };
    render(<CalculatorsSection fileId="f1" />);
    expect(screen.getByRole("button", { name: /Mortgage insurance: Not required/ })).toBeTruthy();
  });

  it("does not let the API's long title back into the visible label", () => {
    // The regression: `data?.title ?? short` put "Mortgage insurance" back on a
    // 9rem tile, and it rendered as "Mortgage insura…".
    titles.value = { mortgage_insurance: "Mortgage insurance" };
    render(<CalculatorsSection fileId="f1" />);
    expect(screen.queryByText("Mortgage insurance")).toBeNull();
  });
});
