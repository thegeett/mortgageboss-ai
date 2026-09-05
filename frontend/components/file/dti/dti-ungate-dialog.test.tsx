/**
 * LP-643 — the ungate dialog, which is a CONSENT rather than a confirmation.
 *
 * What is asserted here is what a processor is shown before they accept an assertion about a file
 * personally: every line by name, what each zero claims, the ratio they will get, and what will NOT
 * move. "Are you sure" would pass a smoke test and tell them nothing.
 */

// @vitest-environment jsdom
// `fireEvent`, not user-event — the latter is not a dependency of this repo, and the existing DTI
// tests drive interaction the same way.
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const applyMutate = vi.fn();
const usePreviewMock = vi.fn();

vi.mock("@/lib/api/dti", () => ({
  useDtiUngatePreview: () => usePreviewMock(),
  useApplyDtiUngate: () => ({ mutate: applyMutate, isPending: false }),
}));

import { DtiUngateDialog } from "./dti-ungate-dialog";

const PREVIEW = {
  lines: [
    {
      key: "housing.taxes",
      label: "Property taxes",
      assertion:
        "Property taxes will be recorded as $0.00/month — the DTI will be computed as if this file has no property taxes obligation.",
    },
  ],
  unresolved: [],
  front_end_before: null,
  back_end_before: null,
  front_end_after: "12.10",
  back_end_after: "34.90",
};

function open(preview: unknown) {
  usePreviewMock.mockReturnValue({ data: preview, isPending: false });
  return render(<DtiUngateDialog fileId="LF-1" open onOpenChange={() => {}} />);
}

afterEach(cleanup);

describe("the ungate dialog", () => {
  it("names every line and what its zero asserts, not a count", () => {
    open(PREVIEW);

    expect(screen.getByText("Property taxes")).toBeDefined();
    // The ASSERTION, not the mechanism — the half a processor can judge as true or false.
    expect(screen.getByText(/computed as if this file has no property taxes/i)).toBeDefined();
    // And never an aggregate, which is what makes it a click-through.
    expect(screen.queryByText(/1 value/i)).toBeNull();
  });

  it("shows the ratio the apply will produce", () => {
    open(PREVIEW);

    // The number is what the consent is really about, so it is on the screen before they agree.
    expect(screen.getByText(/34\.90/)).toBeDefined();
  });

  it("says what will NOT move, rather than leaving a processor to discover it", () => {
    open({
      ...PREVIEW,
      lines: [],
      unresolved: ["no document on the file states what the subject will rent for"],
    });

    expect(screen.getByText(/cannot be resolved by recording zeros/i)).toBeDefined();
    expect(screen.getByText(/what the subject will rent for/i)).toBeDefined();
  });

  it("refuses to apply when there is nothing it can record", () => {
    open({ ...PREVIEW, lines: [], unresolved: ["the rental gate"] });

    // Disabled rather than applying an empty change and leaving them to wonder if it worked.
    expect(
      (screen.getByRole("button", { name: /record as \$0\.00/i }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });

  it("passes the processor's reason through, so the file records why", () => {
    open(PREVIEW);

    fireEvent.change(screen.getByLabelText(/why/i), { target: { value: "tax-exempt, confirmed" } });
    fireEvent.click(screen.getByRole("button", { name: /record as \$0\.00/i }));

    expect(applyMutate).toHaveBeenCalledWith("tax-exempt, confirmed", expect.anything());
  });
});
