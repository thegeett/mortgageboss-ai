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

  it("progressive disclosure: collapsed by default, expands to the four-part detail + source", () => {
    render(
      <FindingCard finding={finding({})} onApply={vi.fn()} onOverride={vi.fn()} onNote={vi.fn()} />,
    );
    // Collapsed: the source snippet + the section headings are hidden.
    expect(screen.queryByText(/Gross 3,775/)).toBeNull();
    expect(screen.queryByText("What we found")).toBeNull();

    // Expand via the Details affordance (labelled with the source page when present).
    fireEvent.click(screen.getByRole("button", { name: /Details · source p\.3/ }));

    // The four-part detail: What we found + Source (the deterministic halves) render.
    expect(screen.getByText("What we found")).toBeDefined();
    expect(screen.getByText("Source")).toBeDefined();
    expect(screen.getByText(/Document page 3/)).toBeDefined();
    expect(screen.getByText(/Gross 3,775/)).toBeDefined(); // the verbatim view-source snippet
  });

  it("graceful degradation: no empty Why-it-matters / Suggested-fix boxes until LP-96 populates them", () => {
    render(
      <FindingCard finding={finding({})} onApply={vi.fn()} onOverride={vi.fn()} onNote={vi.fn()} />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Details/ }));
    // The AI slots are absent (details has no why/fix) → their headings are NOT rendered.
    expect(screen.queryByText("Why it matters")).toBeNull();
    expect(screen.queryByText("Suggested fix")).toBeNull();
    // …while the deterministic halves DO render — the card looks complete + intentional.
    expect(screen.getByText("What we found")).toBeDefined();
    expect(screen.getByText("Source")).toBeDefined();
  });

  it("renders the Why-it-matters + Suggested-fix slots when populated (the LP-96 shape)", () => {
    render(
      <FindingCard
        finding={finding({
          details: {
            reasoning: "Docs show less.",
            why_it_matters: "It inflates qualifying income → the DTI is understated.",
            suggested_fix: "Correct the stated income to the documented figure.",
          },
        })}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Details/ }));
    expect(screen.getByText("Why it matters")).toBeDefined();
    expect(screen.getByText(/inflates qualifying income/)).toBeDefined();
    expect(screen.getByText("Suggested fix")).toBeDefined();
    expect(screen.getByText(/Correct the stated income/)).toBeDefined();
  });

  it("a finding with no source still expands (Details, not source-gated) + labels the authority", () => {
    render(
      <FindingCard
        finding={finding({
          rule_id: "xsrc.income.employer_name_consistency",
          origin: "deterministic_rule",
          category: "income",
          source_page: null,
          source_snippet: null,
          message: "Documented employer not among the stated employers: X.",
          details: { reasoning: "Documented employer not among the stated employers: X." },
        })}
        onOverride={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /^Details/ }));
    expect(screen.getByText("What we found")).toBeDefined();
    // Source degrades to the authority (a cross-source check) when there's no document line.
    expect(screen.getByText(/No single document line/)).toBeDefined();
    // LP-92's readable label is intact (it appears in the meta + the Source authority line).
    expect(screen.getAllByText(/Income · Cross-source check/).length).toBeGreaterThan(0);
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
  it("a resolved finding renders COMPACT — no Details expander, no four-part", () => {
    render(
      <FindingCard
        finding={finding({
          resolution_status: "overridden",
          resolution_note: "Documented separately",
        })}
      />,
    );
    // Compact: no progressive-disclosure affordance, and the section headings never render.
    expect(screen.queryByRole("button", { name: /Details/ })).toBeNull();
    expect(screen.queryByText("What we found")).toBeNull();
    expect(screen.getByText(/Documented separately/)).toBeDefined(); // the disposition line
  });

  it("an applied resolved finding shows a compact what-was-done line", () => {
    render(<FindingCard finding={finding({ resolution_status: "applied" })} />);
    expect(screen.getByText(/Applied — incorporated into the file/)).toBeDefined();
  });

  it("Accept-risk acknowledges a real finding (optional rationale) → onAcceptRisk", () => {
    const onAcceptRisk = vi.fn();
    render(
      <FindingCard
        finding={finding({ status: "red" })}
        onAcceptRisk={onAcceptRisk}
        onOverride={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /accept risk/i }));
    // Accept-risk allows an empty rationale (it's optional, distinct from override).
    fireEvent.click(screen.getByRole("button", { name: "Accept risk" }));
    expect(onAcceptRisk).toHaveBeenCalledTimes(1);
  });

  it("Request-docs calls onRequestDocs (creates a needs item)", () => {
    const onRequestDocs = vi.fn();
    render(<FindingCard finding={finding({})} onRequestDocs={onRequestDocs} onNote={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /request docs/i }));
    fireEvent.change(screen.getByLabelText(/What to request/), {
      target: { value: "The 2024 W-2" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Request docs" }));
    expect(onRequestDocs).toHaveBeenCalledWith("The 2024 W-2");
  });

  it("distinguishes deterministic vs AI source-origin + shows the lender overlay", () => {
    const { rerender } = render(
      <FindingCard
        finding={finding({ origin: "deterministic_rule", details: { overlay_applied: "uwm" } })}
      />,
    );
    expect(screen.getByText("deterministic")).toBeDefined();
    expect(screen.getByText(/uwm overlay/)).toBeDefined();
    rerender(<FindingCard finding={finding({ origin: "ai_cross_source" })} />);
    expect(screen.getByText(/AI · novel/)).toBeDefined();
  });

  it("marks a finding whose docs were already requested", () => {
    render(
      <FindingCard
        finding={finding({ details: { docs_requested: { needs_item_id: "n-1" } } })}
        onRequestDocs={vi.fn()}
      />,
    );
    expect(screen.getByText(/docs requested/)).toBeDefined();
    // The request button is disabled once requested.
    expect(screen.getByRole("button", { name: /Requested/ })).toHaveProperty("disabled", true);
  });
});
