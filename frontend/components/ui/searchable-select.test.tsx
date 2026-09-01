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
  // Clicking the field, not focusing it. Focus alone deliberately does NOT open the list: the
  // drawer is a Radix Sheet whose FocusScope focuses the first tabbable node on mount, and this
  // input is it — so `onFocus` popped a 164-option listbox open on every document a processor
  // opened (LP-638 review).
  fireEvent.mouseDown(screen.getByRole("combobox"));
}

function type(text: string) {
  fireEvent.change(screen.getByRole("combobox"), { target: { value: text } });
}

describe("SearchableSelect", () => {
  it("filters as you type", () => {
    // THE REASON THIS EXISTS. A native <select> over 164 document types can only be searched by
    // first letter, so finding "Closing disclosure" means scrolling the whole catalog.
    render(
      <SearchableSelect label="Document type" options={OPTIONS} value={null} onChange={vi.fn()} />,
    );
    open();
    expect(screen.getAllByRole("option")).toHaveLength(5);

    type("clos");

    const shown = screen.getAllByRole("option").map((o) => o.textContent);
    expect(shown).toEqual(["Closing disclosure"]);
  });

  it("matches the underlying slug as well as the label", () => {
    // A processor reading `closing_disclosure` elsewhere in the product can paste it straight in.
    render(
      <SearchableSelect label="Document type" options={OPTIONS} value={null} onChange={vi.fn()} />,
    );
    open();

    type("purchase_agr");

    expect(screen.getAllByRole("option").map((o) => o.textContent)).toEqual(["Purchase agreement"]);
  });

  it("selects on click", () => {
    const onChange = vi.fn();
    render(
      <SearchableSelect label="Document type" options={OPTIONS} value={null} onChange={onChange} />,
    );
    open();
    type("closing");

    fireEvent.mouseDown(screen.getByRole("option"));

    expect(onChange).toHaveBeenCalledWith("closing_disclosure");
  });

  it("selects with the keyboard", () => {
    // Arrow to move, Enter to choose — without this the control is mouse-only, which a native
    // <select> never was.
    const onChange = vi.fn();
    render(
      <SearchableSelect label="Document type" options={OPTIONS} value={null} onChange={onChange} />,
    );
    open();
    type("disclosure");

    fireEvent.keyDown(screen.getByRole("combobox"), { key: "Enter" });

    expect(onChange).toHaveBeenCalledWith("closing_disclosure");
  });

  it("moves the highlight with the arrow keys", () => {
    const onChange = vi.fn();
    render(
      <SearchableSelect label="Document type" options={OPTIONS} value={null} onChange={onChange} />,
    );
    open();

    fireEvent.keyDown(screen.getByRole("combobox"), { key: "ArrowDown" });
    fireEvent.keyDown(screen.getByRole("combobox"), { key: "Enter" });

    // The second option, not the first — proving the arrow moved something.
    expect(onChange).toHaveBeenCalledWith("loan_estimate");
  });

  it("says so when nothing matches instead of showing an empty box", () => {
    render(
      <SearchableSelect
        label="Document type"
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
    render(
      <SearchableSelect label="Document type" options={OPTIONS} value="w2" onChange={vi.fn()} />,
    );

    expect((screen.getByRole("combobox") as HTMLInputElement).value).toBe("W-2");
  });

  it("groups options by category", () => {
    render(
      <SearchableSelect label="Document type" options={OPTIONS} value={null} onChange={vi.fn()} />,
    );
    open();

    expect(screen.getByText("Disclosures")).toBeDefined();
    expect(screen.getByText("Income employment")).toBeDefined();
  });

  it("is inert when disabled", () => {
    render(
      <SearchableSelect
        label="Document type"
        options={OPTIONS}
        value={null}
        onChange={vi.fn()}
        disabled
      />,
    );

    expect((screen.getByRole("combobox") as HTMLInputElement).disabled).toBe(true);
  });
});

describe("SearchableSelect — LP-638 review", () => {
  it("does not strand an abandoned search", () => {
    // THE ONE THAT LOOKS LIKE NOTHING WENT WRONG. Closing on an outside click left `query` set.
    // The input correctly reverted to the selected label, so the control looked fine — and then
    // refocusing restored the abandoned search AND its filtered list. On a 164-type catalog a
    // processor comes back to a picker apparently holding one option, with no visible cause.
    render(
      <SearchableSelect label="Document type" options={OPTIONS} value={null} onChange={vi.fn()} />,
    );
    open();
    type("clos");
    expect(screen.getAllByRole("option")).toHaveLength(1);

    fireEvent.mouseDown(document.body); // click away
    open(); // and come back

    expect((screen.getByRole("combobox") as HTMLInputElement).value).toBe("");
    expect(screen.getAllByRole("option")).toHaveLength(OPTIONS.length);
  });

  it("clears the search on Escape too, not just the list", () => {
    render(
      <SearchableSelect label="Document type" options={OPTIONS} value={null} onChange={vi.fn()} />,
    );
    open();
    type("clos");
    fireEvent.keyDown(screen.getByRole("combobox"), { key: "Escape" });
    open();

    expect(screen.getAllByRole("option")).toHaveLength(OPTIONS.length);
  });

  it("has an accessible name", () => {
    // The two `useSemanticElements` suppressions are correct — ARIA 1.2's combobox pattern is the
    // right one for a control a native <select> cannot provide. But defending the suppressions is
    // not the same as being accessible: the first version had no `aria-label` and no
    // `aria-labelledby`, so a screen reader announced an unnamed combobox. `label` is a required
    // prop now, so a future caller cannot repeat it.
    render(
      <SearchableSelect label="Document type" options={OPTIONS} value={null} onChange={vi.fn()} />,
    );
    expect(screen.getByRole("combobox", { name: "Document type" })).toBeDefined();
  });

  it("points aria-activedescendant at the option it highlights", () => {
    // Present is not the same as correct. The id has to resolve to the element that is actually
    // highlighted, or the announcement and the screen disagree.
    render(
      <SearchableSelect
        id="t"
        label="Document type"
        options={OPTIONS}
        value={null}
        onChange={vi.fn()}
      />,
    );
    open();
    const input = screen.getByRole("combobox");
    fireEvent.keyDown(input, { key: "ArrowDown" });

    const activeId = input.getAttribute("aria-activedescendant");
    expect(activeId).toBe("t-option-1");
    const highlighted = document.getElementById(activeId ?? "");
    expect(highlighted?.getAttribute("role")).toBe("option");
    expect(highlighted?.textContent).toBe(screen.getAllByRole("option")[1]?.textContent);
  });

  it("does not present group headers as list content", () => {
    // A bare div inside a listbox is not a valid child, and announcing the header would interleave
    // it with the options.
    render(
      <SearchableSelect
        label="Document type"
        options={[
          { value: "a", label: "A", group: "Income" },
          { value: "b", label: "B", group: "Assets" },
        ]}
        value={null}
        onChange={vi.fn()}
      />,
    );
    open();

    const listbox = screen.getByRole("listbox");
    // Two options plus two headers — asserted, so the loop below cannot pass by being empty.
    expect(listbox.children).toHaveLength(4);
    for (const child of Array.from(listbox.children)) {
      const role = child.getAttribute("role");
      expect(role === "option" || role === "presentation").toBe(true);
    }
  });
});

describe("SearchableSelect — it must not open itself", () => {
  it("stays closed when focus merely lands on it", () => {
    // THE BUG A DRAWER MAKES CERTAIN. `SheetContent` is a Radix Dialog whose FocusScope focuses the
    // first tabbable node on mount, and in this drawer that is this input — everything above it is
    // headings and divs. With `onFocus` opening the list, opening ANY document popped a 164-option
    // listbox over the drawer body. It only looked intermittent because a cold types cache leaves
    // the input disabled, and therefore untabbable, on the very first open.
    render(
      <SearchableSelect label="Document type" options={OPTIONS} value={null} onChange={vi.fn()} />,
    );

    fireEvent.focus(screen.getByRole("combobox"));

    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("opens on a click, and again after a choice without moving focus away", () => {
    // Choosing preventDefaults the option's mousedown so focus never leaves the input. With only
    // `onFocus` to open on, clicking the field afterwards fired nothing and the control was dead
    // until the processor clicked elsewhere first.
    const onChange = vi.fn();
    render(
      <SearchableSelect label="Document type" options={OPTIONS} value={null} onChange={onChange} />,
    );
    open();
    fireEvent.mouseDown(screen.getAllByRole("option")[0] as HTMLElement);
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("listbox")).toBeNull();

    open();

    expect(screen.getByRole("listbox")).toBeDefined();
  });

  it("opens on typing, for someone who tabbed in", () => {
    render(
      <SearchableSelect label="Document type" options={OPTIONS} value={null} onChange={vi.fn()} />,
    );
    type("clos");
    expect(screen.getByRole("listbox")).toBeDefined();
  });

  it("tells its ancestor when the list is open, so Escape can be arbitrated", () => {
    // MEASURED, NOT ASSUMED. Stopping the event inside this component does NOT save the drawer:
    // Radix binds Escape on `document` in the capture phase, so it has already run by the time any
    // handler here is reached. A probe with a capture listener registered before mount confirmed it
    // still fires. So the ancestor has to stand down instead, and the only thing that makes that
    // possible is this component saying when it is open.
    const onOpenChange = vi.fn();
    render(
      <SearchableSelect
        label="Document type"
        options={OPTIONS}
        value={null}
        onChange={vi.fn()}
        onOpenChange={onOpenChange}
      />,
    );

    open();
    expect(onOpenChange).toHaveBeenLastCalledWith(true);

    fireEvent.keyDown(screen.getByRole("combobox"), { key: "Escape" });
    expect(onOpenChange).toHaveBeenLastCalledWith(false);
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("wires the ARIA contract even when no id is given", () => {
    // `aria-controls`, `aria-activedescendant`, the option ids and the highlight-scroll all hang
    // off `id`. It was optional, so omitting it produced a combobox that announced no active
    // option and did not follow the keyboard, with nothing failing.
    render(
      <SearchableSelect label="Document type" options={OPTIONS} value={null} onChange={vi.fn()} />,
    );
    open();
    const input = screen.getByRole("combobox");
    fireEvent.keyDown(input, { key: "ArrowDown" });

    const activeId = input.getAttribute("aria-activedescendant");
    expect(activeId).toBeTruthy();
    expect(document.getElementById(activeId ?? "")?.getAttribute("role")).toBe("option");
    expect(input.getAttribute("aria-controls")).toBe(screen.getByRole("listbox").id);
  });
});
