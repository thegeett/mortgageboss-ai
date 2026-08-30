// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DEFAULT_SPLIT, type PaneSplit, ReviewerShell, clampSplit } from "./reviewer-shell";

afterEach(cleanup);

function renderShell(split: PaneSplit | null, onSplitChange = vi.fn()) {
  render(
    <ReviewerShell
      split={split}
      onSplitChange={onSplitChange}
      list={<p>LIST</p>}
      canvas={<p>CANVAS</p>}
      fields={<p>FIELDS</p>}
    />,
  );
  return onSplitChange;
}

describe("clampSplit", () => {
  it("keeps every pane reachable", () => {
    // The server validator enforces this too; the browser clamps so a drag
    // cannot even ASK for a layout with a pane nobody can grab back.
    expect(clampSplit([0, 0])).toEqual([10, 10]);
    expect(clampSplit([95, 95])).toEqual([80, 10]);
  });

  it("leaves the fields pane at least a tenth", () => {
    const [list, canvas] = clampSplit([60, 60]);
    expect(list + canvas).toBeLessThanOrEqual(90);
  });

  it("leaves a sane split alone", () => {
    expect(clampSplit([22, 53])).toEqual([22, 53]);
  });

  it("returns whole percentages", () => {
    const [list, canvas] = clampSplit([22.4187, 53.9]);
    expect(Number.isInteger(list)).toBe(true);
    expect(Number.isInteger(canvas)).toBe(true);
  });
});

describe("ReviewerShell (LP-UI-030)", () => {
  it("renders the three panes", () => {
    renderShell(null);
    expect(screen.getByText("LIST")).toBeTruthy();
    expect(screen.getByText("CANVAS")).toBeTruthy();
    expect(screen.getByText("FIELDS")).toBeTruthy();
  });

  it("uses its own default when the user has never adjusted it", () => {
    // `null` means never adjusted, which is not the same as "adjusted back to
    // the default" — the shell shows its default rather than writing one.
    const onChange = renderShell(null);
    expect(onChange).not.toHaveBeenCalled();
    const list = screen.getAllByRole("separator")[0] as HTMLElement;
    expect(list.getAttribute("aria-valuenow")).toBe(String(DEFAULT_SPLIT[0]));
  });

  it("honours a stored split", () => {
    renderShell([30, 45]);
    const separators = screen.getAllByRole("separator") as HTMLElement[];
    expect(separators[0]?.getAttribute("aria-valuenow")).toBe("30");
    expect(separators[1]?.getAttribute("aria-valuenow")).toBe("45");
  });

  it("moves a divider from the keyboard", () => {
    // A processor reviewing forty fields is already on the keyboard. A layout
    // control that needs a mouse breaks that rhythm.
    const onChange = renderShell([30, 45]);
    const list = screen.getAllByRole("separator")[0] as HTMLElement;
    fireEvent.keyDown(list, { key: "ArrowRight" });
    expect(onChange).toHaveBeenCalledWith([32, 45]);
  });

  it("cannot be nudged past the point where a pane disappears", () => {
    const onChange = renderShell([10, 45]);
    const list = screen.getAllByRole("separator")[0] as HTMLElement;
    fireEvent.keyDown(list, { key: "ArrowLeft" });
    expect(onChange).toHaveBeenCalledWith([10, 45]);
  });

  it("announces each divider as adjustable", () => {
    renderShell([30, 45]);
    for (const separator of screen.getAllByRole("separator")) {
      expect(separator.getAttribute("aria-valuemin")).toBeTruthy();
      expect(separator.getAttribute("aria-valuemax")).toBeTruthy();
      expect(separator.getAttribute("tabindex")).toBe("0");
    }
  });
});
