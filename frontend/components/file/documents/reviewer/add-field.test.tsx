// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AddField } from "./add-field";

afterEach(cleanup);

const FIELDS = ["pay_date", "pay_frequency", "ytd_gross"];

describe("AddField (LP-703)", () => {
  it("offers nothing when there is nothing to add", () => {
    // An untyped document has no declared field set, and one whose extraction
    // already carries every declared field has nothing left. A control that opens
    // onto no choices is worse than no control.
    const { container } = render(<AddField fields={[]} onAdd={vi.fn()} />);
    expect(container.textContent).toBe("");
  });

  it("is collapsed until it is asked for", () => {
    render(<AddField fields={FIELDS} onAdd={vi.fn()} />);
    expect(screen.getByText(/Add a field the extraction missed/)).toBeTruthy();
    expect(screen.queryByLabelText("Which field")).toBeNull();
  });

  it("offers the declared fields as a PICK, never as free text", () => {
    /**
     * The rule the whole component exists for. A key outside the document type's
     * declared set is data no rule can ever read, so a text box here would let a
     * processor type a value into a field that reaches nobody — and the file would
     * look more complete for it.
     */
    render(<AddField fields={FIELDS} onAdd={vi.fn()} />);
    fireEvent.click(screen.getByText(/Add a field the extraction missed/));
    const picker = screen.getByLabelText("Which field");
    expect(picker.tagName).toBe("SELECT");
    expect([...picker.querySelectorAll("option")].map((o) => o.getAttribute("value"))).toEqual([
      "",
      ...FIELDS,
    ]);
  });

  it("will not submit without both a field and a value", () => {
    const onAdd = vi.fn();
    render(<AddField fields={FIELDS} onAdd={onAdd} />);
    fireEvent.click(screen.getByText(/Add a field the extraction missed/));
    const button = screen.getByRole("button", { name: "Add" });

    expect(button).toHaveProperty("disabled", true);
    fireEvent.change(screen.getByLabelText("Which field"), { target: { value: "pay_date" } });
    expect(button).toHaveProperty("disabled", true);
    fireEvent.change(screen.getByLabelText(/What it says/), { target: { value: "  " } });
    expect(button).toHaveProperty("disabled", true);

    fireEvent.change(screen.getByLabelText(/What it says/), { target: { value: "2026-01-31" } });
    expect(button).toHaveProperty("disabled", false);
    fireEvent.click(button);
    expect(onAdd).toHaveBeenCalledWith("pay_date", "2026-01-31");
  });

  it("trims what was typed", () => {
    const onAdd = vi.fn();
    render(<AddField fields={FIELDS} onAdd={onAdd} />);
    fireEvent.click(screen.getByText(/Add a field the extraction missed/));
    fireEvent.change(screen.getByLabelText("Which field"), { target: { value: "ytd_gross" } });
    fireEvent.change(screen.getByLabelText(/What it says/), { target: { value: "  54600.00 " } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    expect(onAdd).toHaveBeenCalledWith("ytd_gross", "54600.00");
  });

  it("says the value will be read by the checks, and that it can be undone", () => {
    // UI COPY IS AN UNTESTED CLAIM unless something asserts it. Both halves are
    // true of the code as built: an added field enters the snapshot the rule
    // engine reads (`build_document_fields`), and `revert_review` withdraws it —
    // reachable from the row's Undo since this ticket.
    render(<AddField fields={FIELDS} onAdd={vi.fn()} />);
    fireEvent.click(screen.getByText(/Add a field the extraction missed/));
    expect(screen.getByText(/checks will read this/)).toBeTruthy();
    expect(screen.getByText(/can be undone/)).toBeTruthy();
  });

  it("closes on Escape, so the keyboard loop is never trapped", () => {
    render(<AddField fields={FIELDS} onAdd={vi.fn()} />);
    fireEvent.click(screen.getByText(/Add a field the extraction missed/));
    fireEvent.keyDown(screen.getByLabelText("Which field"), { key: "Escape" });
    expect(screen.queryByLabelText("Which field")).toBeNull();
  });
});
