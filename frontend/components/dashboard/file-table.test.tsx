// @vitest-environment jsdom
import type { LoanFileSummary } from "@/lib/types/loan-file";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

// The dialog has its own tests; stub it so the table test stays focused on wiring.
vi.mock("@/components/file/delete-file-dialog", () => ({
  DeleteFileDialog: ({ open, file }: { open: boolean; file: { display_id: string } | null }) =>
    open ? <div data-testid="delete-dialog">deleting {file?.display_id}</div> : null,
}));

import { COLUMNS, FileTable } from "./file-table";

const FILE: LoanFileSummary = {
  id: "uuid-1",
  display_id: "LF-1234",
  status: "in_processing",
  loan_program: "conventional",
  loan_purpose: "purchase",
  loan_amount: null,
  lender_id: null,
  lender_name: "Acme Lending",
  property_address: "123 Main St",
  primary_borrower_name: "Mahesh Chhotala",
  created_at: "2026-06-01T00:00:00Z",
  updated_at: "2026-06-20T00:00:00Z",
};

function files(n: number): LoanFileSummary[] {
  return Array.from({ length: n }, (_, i) => ({
    ...FILE,
    id: `uuid-${i}`,
    display_id: `LF-${1000 + i}`,
    primary_borrower_name: `Borrower ${i}`,
  }));
}

function renderTable(over: Partial<React.ComponentProps<typeof FileTable>> = {}) {
  const onSelect = vi.fn();
  render(
    <FileTable
      files={[FILE]}
      isPending={false}
      isError={false}
      isFiltered={false}
      onSelect={onSelect}
      onNewFile={vi.fn()}
      {...over}
    />,
  );
  return { onSelect };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("FileTable — delete action", () => {
  it("renders a per-row actions trigger", () => {
    renderTable();
    expect(screen.getByRole("button", { name: /actions for LF-1234/i })).toBeDefined();
  });

  it("clicking the actions trigger does NOT navigate (stops propagation)", () => {
    const { onSelect } = renderTable();
    fireEvent.click(screen.getByRole("button", { name: /actions for LF-1234/i }));
    // The row navigates on click; the menu must not trigger it.
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("clicking the row body navigates to the file", () => {
    const { onSelect } = renderTable();
    fireEvent.click(screen.getByText("123 Main St"));
    expect(onSelect).toHaveBeenCalledWith(FILE);
  });

  it("does not show the delete dialog until an action is taken", () => {
    renderTable();
    expect(screen.queryByTestId("delete-dialog")).toBeNull();
  });

  it("selecting Delete from the menu opens the dialog and never navigates", () => {
    const { onSelect } = renderTable();
    // Open the menu (Radix opens on pointerdown), then choose Delete file.
    const trigger = screen.getByRole("button", { name: /actions for LF-1234/i });
    fireEvent.pointerDown(trigger, { button: 0 });
    fireEvent.click(trigger);
    fireEvent.click(screen.getByText("Delete file"));

    expect(screen.getByTestId("delete-dialog")).toBeDefined();
    // The whole point of the fix: choosing a row action must not navigate the row.
    expect(onSelect).not.toHaveBeenCalled();
  });
});

describe("FileTable — grid keyboard navigation (LP-UI-007)", () => {
  const rows = () => screen.getAllByRole("row").slice(1); // drop the header row
  /** Indexed access under `noUncheckedIndexedAccess`; a missing row is a test bug. */
  const row = (i: number): HTMLElement => {
    const found = rows()[i];
    if (!found) throw new Error(`row ${i} does not exist (${rows().length} rows rendered)`);
    return found;
  };
  const activeRow = (): HTMLElement => {
    const found = rows().find((r) => r.getAttribute("tabindex") === "0");
    if (!found) throw new Error("no row is tabbable — the grid is unreachable by keyboard");
    return found;
  };

  it("is ONE tab stop for the whole grid, not one per row", () => {
    renderTable({ files: files(8) });
    const tabbable = rows().filter((r) => r.getAttribute("tabindex") === "0");
    expect(tabbable).toHaveLength(1);
    expect(rows()).toHaveLength(8);
    // The other seven are reachable by arrow key, not by Tab.
    expect(rows().filter((r) => r.getAttribute("tabindex") === "-1")).toHaveLength(7);
  });

  it("keeps the row menu out of the tab order too", () => {
    renderTable({ files: files(4) });
    for (const button of screen.getAllByRole("button", { name: /actions for/i })) {
      expect(button.getAttribute("tabindex")).toBe("-1");
    }
  });

  it("ArrowDown moves the tab stop to the next row", () => {
    renderTable({ files: files(5) });
    fireEvent.keyDown(row(0), { key: "ArrowDown" });
    expect(row(1).getAttribute("tabindex")).toBe("0");
    expect(row(0).getAttribute("tabindex")).toBe("-1");
  });

  it("ArrowUp moves it back, and stops at the first row", () => {
    renderTable({ files: files(5) });
    fireEvent.keyDown(row(0), { key: "ArrowDown" });
    fireEvent.keyDown(row(1), { key: "ArrowUp" });
    expect(row(0).getAttribute("tabindex")).toBe("0");
    fireEvent.keyDown(row(0), { key: "ArrowUp" });
    expect(row(0).getAttribute("tabindex")).toBe("0"); // no wrap, no crash
  });

  it("Home and End jump to the ends", () => {
    renderTable({ files: files(6) });
    fireEvent.keyDown(row(0), { key: "End" });
    expect(row(5).getAttribute("tabindex")).toBe("0");
    fireEvent.keyDown(row(5), { key: "Home" });
    expect(row(0).getAttribute("tabindex")).toBe("0");
  });

  it("ArrowDown stops at the last row rather than wrapping", () => {
    renderTable({ files: files(3) });
    for (let i = 0; i < 5; i++) {
      fireEvent.keyDown(activeRow(), { key: "ArrowDown" });
    }
    expect(row(2).getAttribute("tabindex")).toBe("0");
  });

  it("Enter opens the focused row, not the first one", () => {
    const { onSelect } = renderTable({ files: files(4) });
    fireEvent.keyDown(row(0), { key: "ArrowDown" });
    fireEvent.keyDown(row(1), { key: "ArrowDown" });
    fireEvent.keyDown(row(2), { key: "Enter" });
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect.mock.calls[0]?.[0]?.display_id).toBe("LF-1002");
  });

  it("carries grid semantics so position is announced", () => {
    renderTable({ files: files(3) });
    const grid = screen.getByRole("grid", { name: /loan files/i });
    expect(grid.getAttribute("aria-rowcount")).toBe("4"); // 3 rows + header
    expect(grid.getAttribute("aria-colcount")).toBe("10");
    expect(row(0).getAttribute("aria-rowindex")).toBe("2"); // header is row 1
    const cells = row(0).querySelectorAll("[aria-colindex]");
    expect(cells).toHaveLength(10);
    expect(cells[0]?.getAttribute("aria-colindex")).toBe("1");
  });

  it("clamps the tab stop when filtering shrinks the list under it", () => {
    const { rerender } = render(
      <FileTable
        files={files(6)}
        isPending={false}
        isError={false}
        isFiltered={false}
        onSelect={vi.fn()}
        onNewFile={vi.fn()}
      />,
    );
    fireEvent.keyDown(row(0), { key: "End" }); // tab stop on row 6
    rerender(
      <FileTable
        files={files(2)}
        isPending={false}
        isError={false}
        isFiltered
        onSelect={vi.fn()}
        onNewFile={vi.fn()}
      />,
    );
    // Row 6 is gone. Exactly one row must still be tabbable, or the grid
    // becomes unreachable by keyboard entirely.
    expect(rows().filter((r) => r.getAttribute("tabindex") === "0")).toHaveLength(1);
  });

  it("does not answer keys pressed on the row-actions button", () => {
    // The handler is bound on the <tr>, so a keydown on the button bubbles to it.
    // Unhandled, the row's Enter case ran `preventDefault()` + navigate, so the
    // ONLY keyboard route to the menu — ArrowRight, since the button is
    // tabIndex={-1} — led to the loan file instead. Delete file was unreachable.
    const { onSelect } = renderTable({ files: files(3) });
    fireEvent.keyDown(row(0), { key: "ArrowRight" });
    const trigger = screen.getAllByRole("button", { name: /^Actions for / })[0];
    if (!trigger) throw new Error("no row-actions trigger rendered");
    expect(document.activeElement).toBe(trigger);

    fireEvent.keyDown(trigger, { key: "Enter" });
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("does not move the roving stop out from under the focused button", () => {
    renderTable({ files: files(3) });
    fireEvent.keyDown(row(0), { key: "ArrowRight" });
    const trigger = screen.getAllByRole("button", { name: /^Actions for / })[0];
    if (!trigger) throw new Error("no row-actions trigger rendered");
    fireEvent.keyDown(trigger, { key: "ArrowDown" });
    expect(activeRow()).toBe(row(0));
  });

  it("ArrowLeft from the button returns focus to its row", () => {
    // `move()` now early-returns when the index is unchanged, and the row it
    // returns to is almost always already the active one — so this path focuses
    // the row directly rather than relying on a state change.
    renderTable({ files: files(3) });
    fireEvent.keyDown(row(0), { key: "ArrowRight" });
    const trigger = screen.getAllByRole("button", { name: /^Actions for / })[0];
    if (!trigger) throw new Error("no row-actions trigger rendered");
    fireEvent.keyDown(trigger, { key: "ArrowLeft" });
    expect(document.activeElement).toBe(row(0));
  });

  it("does not steal focus after a no-op move followed by a refetch", () => {
    // `move()` used to arm `shouldFocus` before `setActive`. When the target
    // equalled the current index — ArrowUp on row 0, End on the last row, both
    // reachable by holding a key — React bailed out, the effect never ran to
    // clear the flag, and the NEXT `active` change (the `[count]` clamp on a
    // refetch) pulled focus onto a row. That is the yank the hook exists to
    // prevent: a processor typing in the search box loses the caret.
    const props = {
      isPending: false,
      isError: false,
      isFiltered: false,
      onSelect: vi.fn(),
      onNewFile: vi.fn(),
    };
    const { rerender } = render(<FileTable files={files(6)} {...props} />);
    fireEvent.keyDown(row(0), { key: "End" }); // real move: lands on the last row
    fireEvent.keyDown(activeRow(), { key: "End" }); // no-op: already there

    const search = document.createElement("input");
    document.body.appendChild(search);
    search.focus();
    expect(document.activeElement).toBe(search);

    rerender(<FileTable files={files(2)} {...props} isFiltered />);
    expect(document.activeElement).toBe(search);
    search.remove();
  });
});

describe("FileTable — the attention stripe (LP-UI-013)", () => {
  const rows = () => screen.getAllByRole("row").slice(1);

  function withAttention(tone: string, label = "2 findings block submission") {
    return {
      ...FILE,
      attention: { tone, label, needs_total: 4, needs_satisfied: 1 },
    } as unknown as LoanFileSummary;
  }

  it("paints the row's stripe from its tone", () => {
    // Asserted on the RENDERED ROW, not on ATTENTION_STRIPE. A map test leaves
    // the table free to stop reading the map — LP-UI-011's lesson, where
    // exactly that mutation survived four tests of the helper.
    renderTable({ files: [withAttention("blocking")] });
    const cell = rows()[0]?.firstElementChild;
    expect(cell?.className).toContain("border-l-destructive");
  });

  it("uses a different stripe for a calm file", () => {
    renderTable({ files: [withAttention("verified", "Nothing outstanding")] });
    expect(rows()[0]?.firstElementChild?.className).toContain("border-l-success");
  });

  it("emits a LITERAL colour class, not an interpolated one", () => {
    // The defect this ticket shipped and caught: `[&>*:first-child]:${MAP[tone]}`
    // is never emitted by Tailwind, so the stripe renders as the default border
    // and nothing fails. A leftover brace is what that looks like in the DOM.
    renderTable({ files: [withAttention("attention", "Waiting on 3 documents")] });
    const className = rows()[0]?.firstElementChild?.className ?? "";
    expect(className).not.toContain("$");
    expect(className).not.toContain("{");
  });

  it("renders the attention sentence, not the tone", () => {
    renderTable({ files: [withAttention("blocking")] });
    expect(screen.getByText("2 findings block submission")).toBeDefined();
  });

  it("says nothing rather than 'clear' when the backend sent no attention", () => {
    renderTable({ files: [FILE] });
    expect(screen.queryByText(/nothing outstanding/i)).toBeNull();
  });
});

describe("FileTable — the column ladder reaches every cell", () => {
  /**
   * The ladder is applied in THREE places: the header, the body cells, and the
   * skeleton row. The header and the skeleton both map `COLUMNS` and cannot
   * drift; the body cells are written out one per column, and a cell whose
   * visibility class was missed would keep its data while its header vanished —
   * a row misaligned against its own header, at one width, silently.
   *
   * Reading `COLUMNS` and the source cannot see this. Comparing the RENDERED
   * header cell to the RENDERED body cell at the same `aria-colindex` can, and it
   * is the comparison the guarantee is actually about.
   */
  const visibility = (el: Element) =>
    (el.className.match(/(?:^|\s)(?:hidden|[a-z0-9]+:(?:table-cell|block|hidden))(?=\s|$)/g) ?? [])
      .map((c) => c.trim())
      .sort();

  it("each body cell hides at exactly the width its header does", () => {
    renderTable();
    const rows = screen.getAllByRole("row");
    const header = rows[0];
    const body = rows.find((r) => r !== header && r.querySelector('[aria-colindex="1"]'));
    expect(header, "no header row").toBeDefined();
    expect(body, "no body row — the comparison would be vacuous").toBeDefined();

    let compared = 0;
    for (let index = 1; index <= COLUMNS.length; index++) {
      const head = header?.querySelector(`[aria-colindex="${index}"]`);
      const cell = body?.querySelector(`[aria-colindex="${index}"]`);
      if (!head || !cell) continue;
      compared++;
      expect(visibility(cell), `column ${index} (${COLUMNS[index - 1]?.label})`).toEqual(
        visibility(head),
      );
    }
    // The positive control: an empty comparison passes every assertion above.
    expect(compared).toBe(COLUMNS.length);
  });
});
