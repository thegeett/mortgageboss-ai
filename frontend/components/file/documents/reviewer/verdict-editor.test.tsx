// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { VerdictEditor } from "./verdict-editor";

afterEach(cleanup);

function open(overrides: Partial<Parameters<typeof VerdictEditor>[0]> = {}) {
  const handlers = {
    onCorrect: vi.fn(),
    onReject: vi.fn(),
    onRemove: vi.fn(),
    onCancel: vi.fn(),
  };
  render(
    <VerdictEditor fieldLabel="Gross pay" currentValue="54600.00" {...handlers} {...overrides} />,
  );
  return handlers;
}

describe("correcting", () => {
  it("starts from what the extraction read", () => {
    open();
    expect(screen.getByLabelText(/Correct Gross pay/)).toHaveProperty("value", "54600.00");
  });

  it("saves the trimmed value", () => {
    const { onCorrect } = open();
    fireEvent.change(screen.getByLabelText(/Correct Gross pay/), {
      target: { value: " 4200.00 " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(onCorrect).toHaveBeenCalledWith("4200.00");
  });

  it("will not save an empty value", () => {
    open();
    fireEvent.change(screen.getByLabelText(/Correct Gross pay/), { target: { value: "   " } });
    expect(screen.getByRole("button", { name: "Save" })).toHaveProperty("disabled", true);
  });
});

describe("the two reason-bearing actions are NOT the same (LP-703)", () => {
  /**
   * The pair is worse than either alone unless the difference is legible.
   * "Can't verify" leaves the model's value in place for the next person to try
   * again; "Not on this document" takes the field out of what the checks read.
   * Collapsing them would let an illegible page delete data.
   */
  it("offers both, distinctly", () => {
    open();
    expect(screen.getByRole("button", { name: /Can.t verify/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /Not on this document/ })).toBeTruthy();
  });

  it("each calls its own handler with the reason", () => {
    const { onReject, onRemove } = open();
    fireEvent.change(screen.getByLabelText(/give a reason/), {
      target: { value: " the page is a scan " },
    });
    fireEvent.click(screen.getByRole("button", { name: /Can.t verify/ }));
    expect(onReject).toHaveBeenCalledWith("the page is a scan");
    expect(onRemove).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: /Not on this document/ }));
    expect(onRemove).toHaveBeenCalledWith("the page is a scan");
  });

  it("BOTH need a reason — the API refuses either without one", () => {
    // The same rule in both places. A disabled button that the server also
    // rejects is a rule; either one alone is a suggestion.
    open();
    expect(screen.getByRole("button", { name: /Can.t verify/ })).toHaveProperty("disabled", true);
    expect(screen.getByRole("button", { name: /Not on this document/ })).toHaveProperty(
      "disabled",
      true,
    );
    fireEvent.change(screen.getByLabelText(/give a reason/), { target: { value: "not printed" } });
    expect(screen.getByRole("button", { name: /Can.t verify/ })).toHaveProperty("disabled", false);
    expect(screen.getByRole("button", { name: /Not on this document/ })).toHaveProperty(
      "disabled",
      false,
    );
  });

  it("says on screen what each one does to the checks", () => {
    // Two buttons that differ ONLY in their effect on the rule engine, and
    // nothing else on the row would say which is which. Both claims are true of
    // the code: `rejected` leaves the field in `build_document_fields`' output,
    // `removed` omits it.
    open();
    expect(screen.getByText(/keeps the extracted value/)).toBeTruthy();
    expect(screen.getByText(/takes the field out/)).toBeTruthy();
    expect(screen.getByText(/Both can be undone/)).toBeTruthy();
  });
});

describe("the keyboard is never trapped", () => {
  it("closes on Escape", () => {
    const { onCancel } = open();
    fireEvent.keyDown(screen.getByLabelText(/Correct Gross pay/), { key: "Escape" });
    expect(onCancel).toHaveBeenCalled();
  });

  it("disables every action while a save is in flight", () => {
    open({ busy: true });
    fireEvent.change(screen.getByLabelText(/give a reason/), { target: { value: "a reason" } });
    for (const name of [/Save/, /Can.t verify/, /Not on this document/]) {
      expect(screen.getByRole("button", { name })).toHaveProperty("disabled", true);
    }
  });
});
