// @vitest-environment jsdom
/**
 * S3-11 (LP-925): a lender's condition settings save as one body, and a code to review is mapped by
 * choosing a library type.
 */
import type { LenderCodeToReview, LenderConditionSettings } from "@/lib/api/lender-settings";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({
  settings: undefined as LenderConditionSettings | undefined,
  codes: [] as LenderCodeToReview[],
  saved: [] as unknown[],
  mapped: [] as unknown[],
}));
vi.mock("@/lib/api/lender-settings", () => ({
  useLenderConditionSettings: () => ({ data: state.settings }),
  useSaveLenderConditionSettings: () => ({
    isPending: false,
    mutate: (b: unknown) => state.saved.push(b),
  }),
  useLenderCodesToReview: () => ({ data: state.codes }),
  useLibraryTypes: () => ({
    data: [{ id: "CR-05", name: "Credit inquiry letter", label: "CR-05 Credit inquiry letter" }],
  }),
  useMapLenderCode: () => ({ isPending: false, mutate: (b: unknown) => state.mapped.push(b) }),
}));

import { LenderConditionSettings as Settings } from "./lender-condition-settings";

afterEach(() => {
  cleanup();
  state.saved = [];
  state.mapped = [];
});

const UWM: LenderConditionSettings = {
  mortgagee_clause: "United Wholesale Mortgage ISAOA, ATIMA PO BOX 202175 FLORENCE, SC 29502",
  clause_from_letter: true,
  upload_cutoff: "20:00",
  upload_cutoff_tz: "America/New_York",
  upload_fields: ["note"],
  lender_orders_final_inspection: true,
  lender_orders_title_insurance_payoffs: false,
  new_files_lender_processing: false,
};

describe("LenderConditionSettings", () => {
  it("is S3-11 and saves every setting in one body", () => {
    state.settings = UWM;
    state.codes = [
      {
        code: "7812",
        example_wording: "Provide signed and dated letter of explanation for the credit inquiry",
        files: 2,
        canonical_type_id: null,
      },
    ];
    render(<Settings lenderId="l1" name="United Wholesale Mortgage" />);
    screen.getByText("Lender settings · used on every file with this lender");
    screen.getByText("From the newest approval letter — not saved yet.");
    screen.getByText("Sun West asks for all three.");
    screen.getByText("2 files");
    fireEvent.click(screen.getByLabelText("Date verified"));
    fireEvent.click(screen.getByLabelText(/Processor Assist/));
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    const { clause_from_letter: _, ...rest } = UWM;
    expect(state.saved).toEqual([
      {
        ...rest,
        upload_fields: ["note", "date_verified"],
        lender_orders_title_insurance_payoffs: true,
      },
    ]);
  });

  it("maps a code by choosing its library type", () => {
    state.settings = UWM;
    state.codes = [
      { code: "7812", example_wording: "LOE for inquiry", files: 1, canonical_type_id: null },
    ];
    render(<Settings lenderId="l1" name="UWM" />);
    fireEvent.change(screen.getByLabelText("Library type for 7812"), {
      target: { value: "CR-05" },
    });
    expect(state.mapped).toEqual([{ code: "7812", canonical_type_id: "CR-05" }]);
  });
});
