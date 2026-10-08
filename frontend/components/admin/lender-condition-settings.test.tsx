// @vitest-environment jsdom
/**
 * S3-11 (LP-925): a lender's condition settings save as one body. LP-965 removed "codes to review":
 * nothing is mapped per lender code any more.
 */
import type { LenderConditionSettings } from "@/lib/api/lender-settings";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({
  settings: undefined as LenderConditionSettings | undefined,
  saved: [] as unknown[],
}));
vi.mock("@/lib/api/lender-settings", () => ({
  useLenderConditionSettings: () => ({ data: state.settings }),
  useSaveLenderConditionSettings: () => ({
    isPending: false,
    mutate: (b: unknown) => state.saved.push(b),
  }),
}));

import { LenderConditionSettings as Settings } from "./lender-condition-settings";

afterEach(() => {
  cleanup();
  state.saved = [];
});

const UWM: LenderConditionSettings = {
  mortgagee_clause: "United Wholesale Mortgage ISAOA, ATIMA PO BOX 202175 FLORENCE, SC 29502",
  clause_from_letter: true,
  upload_cutoff: "20:00",
  upload_cutoff_tz: "America/New_York",
  upload_fields: ["note"],
  lender_orders_final_inspection: true,
  lender_verifies_business_existence: false,
  lender_orders_title_insurance_payoffs: false,
  new_files_lender_processing: false,
};

describe("LenderConditionSettings", () => {
  it("is S3-11 and saves every setting in one body", () => {
    state.settings = UWM;
    render(<Settings lenderId="l1" name="United Wholesale Mortgage" />);
    screen.getByText("Lender settings · used on every file with this lender");
    screen.getByText("From the newest approval letter — not saved yet.");
    screen.getByText("Sun West asks for all three.");
    fireEvent.click(screen.getByLabelText("Date verified"));
    fireEvent.click(screen.getByLabelText(/Processor Assist/));
    fireEvent.click(screen.getByLabelText(/Lender verifies business existence/));
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    const { clause_from_letter: _, ...rest } = UWM;
    expect(state.saved).toEqual([
      {
        ...rest,
        upload_fields: ["note", "date_verified"],
        lender_orders_title_insurance_payoffs: true,
        lender_verifies_business_existence: true,
      },
    ]);
  });

  it("no longer offers lender codes to review (LP-965)", () => {
    state.settings = UWM;
    render(<Settings lenderId="l1" name="United Wholesale Mortgage" />);
    expect(screen.getByText("Lender settings · used on every file with this lender")).toBeTruthy();
    expect(screen.queryByText(/codes to review/i)).toBeNull();
    expect(screen.queryByRole("combobox", { name: /Library type for/ })).toBeNull();
  });
});
