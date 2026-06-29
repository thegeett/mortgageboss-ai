// @vitest-environment jsdom
import type { VerificationFinding } from "@/lib/types/verification";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { FindingCard } from "./finding-card";

function finding(over: Partial<VerificationFinding>): VerificationFinding {
  return {
    id: "f-1",
    rule_id: "cross_source.income_variance",
    origin: "ai_cross_source",
    status: "yellow",
    category: "income",
    message: "Stated income is 8% over the pay stubs.",
    confidence: 0.82,
    source_page: 3,
    source_snippet: "Gross 3,775.00 biweekly",
    resolution_status: "open",
    resolution_note: null,
    details: { apply: { action: "correct_income" }, reasoning: "Docs show less." },
    ...over,
  };
}

afterEach(() => cleanup());

describe("FindingCard", () => {
  it("shows the templated headline + the AI description as secondary detail", () => {
    render(
      <FindingCard finding={finding({})} onApply={vi.fn()} onOverride={vi.fn()} onNote={vi.fn()} />,
    );
    expect(screen.getByText("Stated income doesn’t match the documents")).toBeDefined();
    expect(screen.getByText("Stated income is 8% over the pay stubs.")).toBeDefined();
  });

  it("reveals the source location (page + verbatim snippet) on click", () => {
    render(
      <FindingCard finding={finding({})} onApply={vi.fn()} onOverride={vi.fn()} onNote={vi.fn()} />,
    );
    expect(screen.queryByText(/Gross 3,775/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Source · p\.3/ }));
    expect(screen.getByText(/Document page 3/)).toBeDefined();
    expect(screen.getByText(/Gross 3,775/)).toBeDefined();
  });

  it("Apply calls onApply (the recompute interlock)", () => {
    const onApply = vi.fn();
    render(
      <FindingCard finding={finding({})} onApply={onApply} onOverride={vi.fn()} onNote={vi.fn()} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(onApply).toHaveBeenCalledTimes(1);
  });

  it("Override requires a reason, then calls onOverride with it", () => {
    const onOverride = vi.fn();
    render(
      <FindingCard
        finding={finding({})}
        onApply={vi.fn()}
        onOverride={onOverride}
        onNote={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /override…/i }));
    // The confirm button is disabled until a reason is typed.
    const confirm = screen.getByRole("button", { name: "Override" });
    expect(confirm).toHaveProperty("disabled", true);
    fireEvent.change(screen.getByLabelText(/Reason for dismissing/), {
      target: { value: "Already on the 1003" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Override" }));
    expect(onOverride).toHaveBeenCalledWith("Already on the 1003");
  });

  it("Add note calls onNote with the text", () => {
    const onNote = vi.fn();
    render(
      <FindingCard finding={finding({})} onApply={vi.fn()} onOverride={vi.fn()} onNote={onNote} />,
    );
    fireEvent.click(screen.getByRole("button", { name: /add note/i }));
    fireEvent.change(screen.getByLabelText("Note"), { target: { value: "Asked borrower" } });
    fireEvent.click(screen.getByRole("button", { name: /save note/i }));
    expect(onNote).toHaveBeenCalledWith("Asked borrower");
  });

  it("hides the Apply button when the finding declares no structured change", () => {
    render(
      <FindingCard
        finding={finding({ details: {} })}
        onApply={vi.fn()}
        onOverride={vi.fn()}
        onNote={vi.fn()}
      />,
    );
    expect(screen.queryByRole("button", { name: "Apply" })).toBeNull();
  });

  it("a resolved finding shows its reason and no actions (history)", () => {
    render(
      <FindingCard
        finding={finding({
          resolution_status: "overridden",
          resolution_note: "Documented separately",
        })}
      />,
    );
    expect(screen.getByText(/Documented separately/)).toBeDefined();
    expect(screen.queryByRole("button", { name: /override/i })).toBeNull();
    expect(screen.queryByRole("button", { name: "Apply" })).toBeNull();
  });
});
