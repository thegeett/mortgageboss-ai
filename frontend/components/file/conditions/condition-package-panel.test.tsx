// @vitest-environment jsdom
/**
 * S3-10 (LP-925): the package lists one PDF and one note per ready condition, says what is not in it,
 * and Mark submitted asks before it moves anything. Nothing is uploaded by the app.
 */
import type { ConditionPackage } from "@/lib/types/conditions";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({
  data: undefined as ConditionPackage | null | undefined,
  built: 0,
  submitted: 0,
  rows: [] as unknown[],
  duDone: 0,
}));
vi.mock("@/lib/api/conditions", () => ({
  useConditionPackage: () => ({ data: state.data }),
  useBuildPackage: () => ({ isPending: false, mutate: () => state.built++ }),
  useUpdatePackageRow: () => ({ isPending: false, mutate: (b: unknown) => state.rows.push(b) }),
  useMarkDuRerunDone: () => ({ isPending: false, mutate: () => state.duDone++ }),
  useSubmitPackage: () => ({ isPending: false, mutate: () => state.submitted++ }),
  downloadConditionPackage: vi.fn(async () => undefined),
}));

import { ConditionPackagePanel, minutesUntil } from "./condition-package-panel";

afterEach(() => {
  cleanup();
  state.built = 0;
  state.submitted = 0;
  state.rows = [];
  state.duDone = 0;
});

function row(code: string, file: string | null, pages: number, source: "ai" | "code" | "edited") {
  return {
    condition_id: `c-${code}`,
    code,
    file_name: file,
    document_ids: file ? [`d-${code}`] : [],
    pages,
    note: `Note for ${code}`,
    note_source: source,
    fields: {},
    included: true,
  };
}

const S3_10: ConditionPackage = {
  lender_short: "UWM",
  round_number: 1,
  status: "built",
  package_id: "p1",
  rows: [
    row("7086", "7086 - Assets.pdf", 12, "ai"),
    row("6178", null, 0, "code"),
    row("0006", "0006 - Invoice.pdf", 1, "edited"),
  ],
  ready_count: 3,
  warnings: [
    {
      kind: "open_prior_to_docs",
      code: "1228",
      text: "Provide the final HOA certification",
    },
  ],
  later_codes: ["0007"],
  cutoff: "20:00",
  cutoff_tz: "America/New_York",
  upload_fields: ["note"],
  du_rerun_open: false,
  submitted_at: null,
};

describe("ConditionPackagePanel", () => {
  it("is S3-10", () => {
    state.data = S3_10;
    render(<ConditionPackagePanel fileId="f1" />);
    screen.getByText("Package for UWM · round 1");
    screen.getByText("3 conditions ready · 13 pages");
    screen.getByText("7086 - Assets.pdf");
    screen.getByText("0006 - Invoice.pdf");
    screen.getByText("1228 (prior to docs) is still open");
    screen.getByText(/Docs cannot be drawn until it clears/);
    screen.getByText(/Prior-to-funding items \(0007\) are not included/);
    screen.getByText("drafted · numbers checked by code");
    screen.getByText("written by code");
    screen.getByText("edited by you");
    // Two PDFs: 6178 has no document.
    screen.getByRole("button", { name: /Download package \(2 PDFs \+ notes\)/ });
    screen.getByText(/after you upload in EASE/);
    screen.getByText(/UWM upload cutoff 8:00 PM ET/);
  });

  it("asks before Mark submitted moves anything", () => {
    state.data = S3_10;
    render(<ConditionPackagePanel fileId="f1" />);
    fireEvent.click(screen.getByRole("button", { name: /Mark submitted/ }));
    expect(state.submitted).toBe(0);
    screen.getByText("Move 3 to Sent to lender?");
    fireEvent.click(screen.getByRole("button", { name: "Not yet" }));
    expect(state.submitted).toBe(0);
    fireEvent.click(screen.getByRole("button", { name: /Mark submitted/ }));
    fireEvent.click(screen.getByRole("button", { name: "Mark submitted" }));
    expect(state.submitted).toBe(1);
  });

  it("keeps an edited note and an unticked row", () => {
    state.data = S3_10;
    render(<ConditionPackagePanel fileId="f1" />);
    const note = screen.getByLabelText("Note for 7086");
    fireEvent.change(note, { target: { value: "Her words" } });
    fireEvent.blur(note);
    fireEvent.click(screen.getByLabelText("Include 6178"));
    expect(state.rows).toEqual([
      { conditionId: "c-7086", note: "Her words" },
      { conditionId: "c-6178", included: false },
    ]);
  });

  it("offers Build package before it is built, and nothing when nothing is ready", () => {
    state.data = { ...S3_10, status: null, rows: [], ready_count: 6 };
    const { unmount } = render(<ConditionPackagePanel fileId="f1" />);
    // LP-958 — the Next banner: the count, and the step in a sentence naming the lender.
    screen.getByText(
      /6 conditions are ready to send\. Build the lender package and upload it to UWM\./,
    );
    fireEvent.click(screen.getByRole("button", { name: /Build lender package/ }));
    expect(state.built).toBe(1);
    unmount();
    state.data = { ...S3_10, status: null, rows: [], ready_count: 0 };
    const { container } = render(<ConditionPackagePanel fileId="f1" />);
    expect(container.textContent).toBe("");
  });

  it("offers Mark DU re-run done when DU must be re-run", () => {
    state.data = {
      ...S3_10,
      warnings: [{ kind: "du_rerun", code: "", text: "DTI crossed 45%" }],
      du_rerun_open: true,
    };
    render(<ConditionPackagePanel fileId="f1" />);
    screen.getByText("Re-run DU before submitting.");
    fireEvent.click(screen.getByRole("button", { name: "Mark DU re-run done" }));
    expect(state.duDone).toBe(1);
  });

  it("counts down to the cutoff in the lender's zone", () => {
    // 5:46 PM Eastern on 09/09 (EDT, UTC-4) is 2 h 14 m before 8:00 PM.
    expect(minutesUntil("20:00", "America/New_York", new Date("2026-09-09T21:46:00Z"))).toBe(134);
    expect(minutesUntil("20:00", "Not/AZone", new Date())).toBeNull();
  });
});
