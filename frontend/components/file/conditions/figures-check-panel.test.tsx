// @vitest-environment jsdom
/**
 * S3-09 (LP-924): the figures check shows code's old and new figures, says whether DU must be re-run,
 * and applies exactly the rows on screen — or nothing, on "Not now".
 */
import type { FiguresCheck } from "@/lib/types/conditions";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({
  data: undefined as FiguresCheck | undefined,
  applied: [] as unknown[],
}));
vi.mock("@/lib/api/conditions", () => ({
  useFiguresCheck: () => ({ data: state.data }),
  useApplyFigures: () => ({
    isPending: false,
    mutate: (body: unknown) => state.applied.push(body),
  }),
}));

import { FiguresCheckPanel } from "./figures-check-panel";

afterEach(cleanup);

const S3_09: FiguresCheck = {
  changes: [
    {
      key: "verified_assets",
      label: "Verified assets",
      in_file: "11062.18",
      from_evidence: "41914.42",
      source: "7086 · Capital One ··9912 Jul–Aug",
      unit: "money",
      applies: true,
      condition_codes: ["7086"],
    },
    {
      key: "monthly_insurance",
      label: "Monthly homeowners insurance",
      in_file: "120.00",
      from_evidence: "155.00",
      source: "6178 · new declarations page",
      unit: "money",
      applies: true,
      condition_codes: ["6178"],
    },
    {
      key: "housing_ratio",
      label: "Housing ratio",
      in_file: "32.51",
      from_evidence: "33.12",
      source: "computed",
      unit: "percent",
      applies: false,
      condition_codes: [],
    },
    {
      key: "dti",
      label: "Debt-to-income (DTI)",
      in_file: "40.36",
      from_evidence: "40.97",
      source: "computed · +0.61 points",
      unit: "percent",
      applies: false,
      condition_codes: [],
    },
  ],
  apply_count: 2,
  covers: { verified: "41914.42", required: "38210.40" },
  du_rerun: false,
  du_reasons: [],
  du_not_checked: [],
  citation: "Fannie Mae B3-2-10",
};

describe("FiguresCheckPanel", () => {
  it("is S3-09", () => {
    state.data = S3_09;
    state.applied = [];
    render(<FiguresCheckPanel fileId="f1" />);
    expect(screen.getByText("2 changes from accepted evidence")).toBeDefined();
    for (const text of [
      "$11,062.18",
      "$41,914.42",
      "$120.00",
      "$155.00",
      "32.51%",
      "33.12%",
      "40.36%",
      "40.97%",
    ]) {
      expect(screen.getByText(text)).toBeDefined();
    }
    expect(screen.getByText("computed · +0.61 points")).toBeDefined();
    expect(screen.getByText("Assets now cover closing.")).toBeDefined();
    expect(screen.getByText("DU re-run not needed.")).toBeDefined();
    // LP-936: the old sentence ("DTI stays at or under 45%") was untrue for 46% → 48%, which needs no
    // re-run and is over 45%. It now says what B3-2-10 actually checks.
    expect(
      screen.getByText(/DTI did not cross 45%, is not over 50%, and rose less than 3 points/),
    ).toBeDefined();
    fireEvent.click(screen.getByRole("button", { name: "Apply 2 changes to the file’s figures" }));
    expect(state.applied).toEqual([
      {
        changes: S3_09.changes.map((c) => ({
          key: c.key,
          in_file: c.in_file,
          from_evidence: c.from_evidence,
        })),
      },
    ]);
  });

  it("says Re-run DU when the tolerances are crossed", () => {
    state.data = { ...S3_09, du_rerun: true, du_reasons: ["the DTI rises above 45% (44% → 46%)"] };
    render(<FiguresCheckPanel fileId="f1" />);
    expect(screen.getByText("Re-run DU before submitting.")).toBeDefined();
    expect(screen.getByText(/The DTI rises above 45%/)).toBeDefined();
  });

  it("Not now hides it; nothing to apply shows nothing", () => {
    state.data = S3_09;
    const { container } = render(<FiguresCheckPanel fileId="f1" />);
    fireEvent.click(screen.getByRole("button", { name: "Not now" }));
    expect(container.innerHTML).toBe("");
    cleanup();
    state.data = { ...S3_09, changes: [], apply_count: 0 };
    const again = render(<FiguresCheckPanel fileId="f1" />);
    expect(again.container.innerHTML).toBe("");
  });
});
