// @vitest-environment jsdom
import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useFieldSelection } from "./use-field-selection";

/**
 * The guardrail the ticket calls out, and the reason it gets its own test.
 *
 * "Click the document to fill the field" is how this pattern usually works, and
 * implemented that way a misclick silently replaces a correct income figure with
 * an employer's name — on a compliance file, with no undo the processor knows
 * about. Clicking another field's box NAVIGATES instead.
 */
describe("useFieldSelection — the misclick guardrail (LP-UI-031)", () => {
  it("selects a field when nothing is selected", () => {
    const { result } = renderHook(() => useFieldSelection());
    let outcome: ReturnType<typeof result.current.clickBox> | undefined;
    act(() => {
      outcome = result.current.clickBox("gross_pay");
    });
    expect(outcome).toEqual({ kind: "selected", fieldKey: "gross_pay" });
    expect(result.current.selected).toBe("gross_pay");
  });

  it("NAVIGATES rather than overwriting when another field is selected", () => {
    // THE defect this exists to prevent. The obvious implementation writes
    // "employer_name"'s value into the selected "gross_pay".
    const { result } = renderHook(() => useFieldSelection());
    act(() => {
      result.current.select("gross_pay");
    });
    let outcome: ReturnType<typeof result.current.clickBox> | undefined;
    act(() => {
      outcome = result.current.clickBox("employer_name");
    });
    expect(outcome).toEqual({ kind: "navigated", from: "gross_pay", to: "employer_name" });
    expect(result.current.selected).toBe("employer_name");
  });

  it("treats clicking the selected field's own box as confirmation", () => {
    // Not a navigation: the processor is checking they are looking at the right
    // thing, and reporting that as a navigation would make the distinction
    // useless for anything that acts on it.
    const { result } = renderHook(() => useFieldSelection());
    act(() => {
      result.current.select("gross_pay");
    });
    let outcome: ReturnType<typeof result.current.clickBox> | undefined;
    act(() => {
      outcome = result.current.clickBox("gross_pay");
    });
    expect(outcome).toEqual({ kind: "reselected", fieldKey: "gross_pay" });
  });

  it("never reports a write", () => {
    // The whole point: no outcome of clicking the page is "the value changed".
    const { result } = renderHook(() => useFieldSelection());
    act(() => {
      result.current.select("gross_pay");
    });
    let outcome: ReturnType<typeof result.current.clickBox> | undefined;
    act(() => {
      outcome = result.current.clickBox("employer_name");
    });
    expect(["selected", "navigated", "reselected"]).toContain(outcome?.kind);
  });

  it("tracks hover separately from selection", () => {
    // Hovering a box highlights its field without changing what is selected —
    // otherwise moving the mouse across the page would reassign the review.
    const { result } = renderHook(() => useFieldSelection());
    act(() => {
      result.current.select("gross_pay");
      result.current.hover("employer_name");
    });
    expect(result.current.selected).toBe("gross_pay");
    expect(result.current.hovered).toBe("employer_name");
  });

  it("clears a selection", () => {
    const { result } = renderHook(() => useFieldSelection());
    act(() => {
      result.current.select("gross_pay");
    });
    act(() => {
      result.current.select(null);
    });
    expect(result.current.selected).toBeNull();
  });
});
