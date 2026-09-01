// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { type SearchableOption, SearchableSelect } from "./searchable-select";

afterEach(cleanup);

const OPTIONS: SearchableOption[] = [
  { value: "closing_disclosure", label: "Closing disclosure", group: "Disclosures" },
  { value: "loan_estimate", label: "Loan estimate", group: "Disclosures" },
  { value: "pay_stub", label: "Pay stub", group: "Income employment" },
  { value: "w2", label: "W-2", group: "Income employment" },
  { value: "purchase_agreement", label: "Purchase agreement", group: "Property" },
];

function open() {
  fireEvent.focus(screen.getByRole("combobox"));
}

function type(text: string) {
  fireEvent.change(screen.getByRole("combobox"), { target: { value: text } });
}

describe("SearchableSelect", () => {
  it("filters as you type", () => {
    // THE REASON THIS EXISTS. A native <select> over 164 document types can only be searched by
    // first letter, so finding "Closing disclosure" means scrolling the whole catalog.
    render(<SearchableSelect options={OPTIONS} value={null} onChange={vi.fn()} />);
    open();
    expect(screen.getAllByRole("option")).toHaveLength(5);

    type("clos");

    const shown = screen.getAllByRole("option").map((o) => o.textContent);
    expect(shown).toEqual(["Closing disclosure"]);
  });

  it("matches the underlying slug as well as the label", () => {
    // A processor reading `closing_disclosure` elsewhere in the product can paste it straight in.
    render(<SearchableSelect options={OPTIONS} value={null} onChange={vi.fn()} />);
    open();

    type("purchase_agr");

    expect(screen.getAllByRole("option").map((o) => o.textContent)).toEqual(["Purchase agreement"]);
  });

  it("selects on click", () => {
    const onChange = vi.fn();
    render(<SearchableSelect options={OPTIONS} value={null} onChange={onChange} />);
    open();
    type("closing");

    fireEvent.mouseDown(screen.getByRole("option"));

    expect(onChange).toHaveBeenCalledWith("closing_disclosure");
  });

  it("selects with the keyboard", () => {
    // Arrow to move, Enter to choose — without this the control is mouse-only, which a native
    // <select> never was.
    const onChange = vi.fn();
    render(<SearchableSelect options={OPTIONS} value={null} onChange={onChange} />);
    open();
    type("disclosure");

    fireEvent.keyDown(screen.getByRole("combobox"), { key: "Enter" });

    expect(onChange).toHaveBeenCalledWith("closing_disclosure");
  });

  it("moves the highlight with the arrow keys", () => {
    const onChange = vi.fn();
    render(<SearchableSelect options={OPTIONS} value={null} onChange={onChange} />);
    open();

    fireEvent.keyDown(screen.getByRole("combobox"), { key: "ArrowDown" });
    fireEvent.keyDown(screen.getByRole("combobox"), { key: "Enter" });

    // The second option, not the first — proving the arrow moved something.
    expect(onChange).toHaveBeenCalledWith("loan_estimate");
  });

  it("says so when nothing matches instead of showing an empty box", () => {
    render(
      <SearchableSelect
        options={OPTIONS}
        value={null}
        onChange={vi.fn()}
        emptyMessage="No document type matches"
      />,
    );
    open();

    type("zzzz");

    expect(screen.queryAllByRole("option")).toHaveLength(0);
    expect(screen.getByText("No document type matches")).toBeDefined();
  });

  it("shows the selected label at rest", () => {
    // At rest the control reads as "what is chosen"; typing turns it into "what am I looking for".
    render(<SearchableSelect options={OPTIONS} value="w2" onChange={vi.fn()} />);

    expect((screen.getByRole("combobox") as HTMLInputElement).value).toBe("W-2");
  });

  it("groups options by category", () => {
    render(<SearchableSelect options={OPTIONS} value={null} onChange={vi.fn()} />);
    open();

    expect(screen.getByText("Disclosures")).toBeDefined();
    expect(screen.getByText("Income employment")).toBeDefined();
  });

  it("is inert when disabled", () => {
    render(<SearchableSelect options={OPTIONS} value={null} onChange={vi.fn()} disabled />);

    expect((screen.getByRole("combobox") as HTMLInputElement).disabled).toBe(true);
  });
});
