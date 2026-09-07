// @vitest-environment jsdom
/**
 * The reviewer's MOUSE path, end to end through the page (LP-711 review).
 *
 * LP-703 built correcting, removing, adding and undoing. LP-711 found that none
 * of it could be reached without a keystroke, because `setEditing` was called
 * from exactly two key handlers — a WIRING defect, in this file, between a
 * capability and a control.
 *
 * Everything holding that fix lived one layer below it: the component test
 * asserts an Edit control calls `onEdit`, and `review-queue.test.ts` asserts
 * `editableFieldKey` picks the right field. Both passed for the whole period the
 * feature was unreachable, because neither knows whether this page passes an
 * `onEdit` at all. So the bug is tested where it was seen: click a value, click
 * Edit, type, save, and assert the mutation carries the corrected value.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const recordMutate = vi.fn();
const revertMutate = vi.fn();
const documentsData = vi.hoisted(() => ({ value: undefined as unknown }));
const detailData = vi.hoisted(() => ({ value: undefined as unknown }));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "file-1" }),
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("@/lib/api/documents", () => ({
  useLoanFileDocuments: () => ({ data: documentsData.value }),
  useDocumentDetail: () => ({ data: detailData.value, isPending: false, isError: false }),
}));
vi.mock("@/lib/api/field-boxes", () => ({ useFieldBoxes: () => ({ data: undefined }) }));
vi.mock("@/lib/api/page-image", () => ({
  usePageImage: () => ({ data: undefined, isPending: false, isError: true }),
}));
vi.mock("@/lib/api/preferences", () => ({
  usePreferences: () => ({ data: undefined }),
  useUpdatePreferences: () => ({ mutate: vi.fn() }),
}));
vi.mock("@/lib/api/field-reviews", () => ({
  useRecordFieldReview: () => ({ mutate: recordMutate, isPending: false }),
  useRevertFieldReview: () => ({ mutate: revertMutate, isPending: false }),
}));

import ReviewPage from "./page";

const DOCUMENT = {
  id: "doc-1",
  status: "completed",
  original_filename: "paystub.pdf",
  standard_name: "Pay stub",
  is_current: true,
  superseded_at: null,
  deleted_at: null,
};

afterEach(cleanup);
beforeEach(() => {
  recordMutate.mockClear();
  revertMutate.mockClear();
  documentsData.value = [DOCUMENT];
  detailData.value = {
    id: "doc-1",
    status: "completed",
    field_scrutiny: {},
    addable_fields: [],
    current_extraction: {
      extracted_data: {
        gross_pay: { value: "15,000.00", confidence: 0.4, source: { page: 1, snippet: "Gross" } },
        ytd_gross: { value: "", confidence: null, source: { page: 1, snippet: "YTD" } },
      },
    },
  };
});

/** Select a row the way a processor does — by clicking the value, not the label. */
function clickValue(text: string) {
  const row = screen.getByText(text).closest("li");
  expect(row, `no row showing ${text}`).toBeTruthy();
  fireEvent.click(row as Element);
}

describe("the reviewer's mouse path", () => {
  it("clicking a value, then Edit, records a correction", () => {
    render(<ReviewPage />);
    // Nothing is selected, so nothing offers to be edited.
    expect(screen.queryByRole("button", { name: "Edit" })).toBeNull();

    clickValue("15,000.00");
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));

    // The editor opens on THAT field, prefilled with what the model read.
    const input = screen.getByDisplayValue("15,000.00");
    fireEvent.change(input, { target: { value: "4,200.00" } });
    fireEvent.click(screen.getByRole("button", { name: /^save/i }));

    expect(recordMutate).toHaveBeenCalledTimes(1);
    expect(recordMutate.mock.calls[0]?.[0]).toMatchObject({
      fieldKey: "gross_pay",
      verdict: "corrected",
      correctedValue: "4,200.00",
    });
  });

  it("offers the same path on a field the model returned empty", () => {
    // The field a processor most needs to supply, and the one the mouse could not
    // reach: `AddField` cannot offer it either, because the key is already in the
    // extraction. The keyboard could open an editor on it throughout.
    render(<ReviewPage />);
    const row = screen.getByText("YTD gross").closest("li");
    fireEvent.click(row as Element);
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    expect(screen.getByRole("button", { name: /^save/i })).toBeTruthy();
  });

  it("offers Edit only on the row that is selected", () => {
    // A control on forty rows at once is the chrome LP-UI-032 removed.
    render(<ReviewPage />);
    clickValue("15,000.00");
    expect(screen.getAllByRole("button", { name: "Edit" })).toHaveLength(1);
  });

  it("the E key refuses a table too — the rule, not just the control", () => {
    // THE CONTROL NOT RENDERING IS NOT THE RULE HOLDING. `openEditor` runs every
    // request through `editableFieldKey`, and nothing held that: replacing it with
    // the bare key passed the whole suite, because the mouse test only asks whether
    // a button was drawn and `review-queue.test.ts` tests the rule in isolation
    // from the only caller that matters.
    //
    // What the rule prevents is documented on this page and is severe: `setEditing`
    // on a list mounts no editor while `shortcutsEnabled` has already switched the
    // keyboard off, and every callback that could clear `editing` belongs to the
    // editor that never mounted — so `E` on a table killed the reviewer's keyboard
    // until the page was reloaded.
    detailData.value = {
      ...(detailData.value as object),
      current_extraction: {
        extracted_data: {
          earnings_lines: { value: [{ a: "1" }, { a: "2" }], source: { page: 1, snippet: "t" } },
        },
      },
    };
    render(<ReviewPage />);
    fireEvent.click(screen.getByText("Earnings lines").closest("li") as Element);
    fireEvent.keyDown(window, { key: "e" });
    expect(
      screen.queryByRole("button", { name: /^save/i }),
      "an editor opened on a table",
    ).toBeNull();

    // THE KEYBOARD IS STILL ALIVE, which is the actual damage. `?` opens the
    // shortcut sheet, and it cannot if `editing` was set behind an editor that
    // never mounted.
    fireEvent.keyDown(window, { key: "?" });
    expect(screen.queryByRole("dialog"), "the keyboard was locked out").toBeTruthy();
  });

  it("does not offer Edit for a table, which has no single value to correct", () => {
    // The rule the mouse shares with the keyboard. `editableFieldKey` refuses a
    // list, and `E` on one used to kill the whole keyboard — so the control must
    // not offer a path into the same state.
    detailData.value = {
      ...(detailData.value as object),
      current_extraction: {
        extracted_data: {
          earnings_lines: { value: [{ a: "1" }, { a: "2" }], source: { page: 1, snippet: "t" } },
        },
      },
    };
    render(<ReviewPage />);
    const row = screen.getByText("Earnings lines").closest("li");
    fireEvent.click(row as Element);
    expect(screen.queryByRole("button", { name: "Edit" })).toBeNull();
  });
});
