// @vitest-environment jsdom
import type { RuleFinding } from "@/lib/types/verification";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RuleFindingActions } from "./rule-finding-actions";

afterEach(cleanup);

function finding(overrides: Partial<RuleFinding> = {}): RuleFinding {
  return {
    id: "f1",
    rule_id: "DT-6",
    rule_name: "Stated housing payment vs. servicer's billed payment",
    missing_documents: [],
    can_apply: false,
    evaluation_outcome: "needs_review",
    status: "yellow",
    category: "DTI",
    message: "the application understates this payment",
    subject_key: "lia1",
    subject_label: "Mortgage statement 1013.pdf",
    guideline: null,
    load_bearing_tags: [],
    ratification_pending: true,
    how_to_fix: null,
    confidence: 1,
    resolution_status: "open",
    source_documents: [],
    ...overrides,
  };
}

vi.mock("@/components/file/verification/view-fix-dialog", () => ({
  ViewFixDialog: ({ open }: { open: boolean }) =>
    open ? <div data-testid="view-fix-dialog">before/after</div> : null,
}));

describe("Apply confirms before it writes (LP-577)", () => {
  // Apply WRITES TO THE LOAN and moves an underwriting number — on DT-8 the back-end DTI swings
  // from 58.59% to 34.39%. It must show the itemized before/after first, so a processor confirms a
  // figure rather than discovers it. Undo exists, but it does not help with a wrong Apply nobody
  // noticed.
  it("opens the before/after preview instead of applying immediately", () => {
    const onAct = vi.fn();
    render(
      <RuleFindingActions finding={finding({ can_apply: true })} onAct={onAct} fileId="LF-1" />,
    );

    // fireEvent, not .click(): a raw DOM click does not flush the React state update that opens
    // the dialog, so the assertion below would fail on a component that works.
    // LP-580 — labelled "View fix", not "Apply": the button opens a dry-run and writes nothing, so
    // the label has to say so. The dialog's own "Apply fix" is the one that commits.
    fireEvent.click(screen.getByRole("button", { name: /View fix/i }));

    expect(screen.getByTestId("view-fix-dialog")).toBeDefined();
    expect(onAct).not.toHaveBeenCalled(); // nothing written yet
  });

  it('still reads "Apply" on the fallback path, where it really does apply', () => {
    // The label tracks the CONSEQUENCE, not the component. With no preview to open, the click
    // writes to the loan — calling that "View fix" would be the same lie in the other direction.
    render(<RuleFindingActions finding={finding({ can_apply: true })} onAct={vi.fn()} />);

    expect(screen.getByRole("button", { name: "Apply" })).toBeDefined();
  });

  it("applies directly when no fileId is threaded, rather than losing the button", () => {
    // The prop is optional so a caller that has not threaded it degrades to the old behaviour —
    // which is worse than the preview, but far better than an Apply button that does nothing. That
    // silent-nothing is exactly what a required prop would have produced here, because TypeScript
    // is satisfied by an optional prop that no call site passes.
    const onAct = vi.fn();
    render(<RuleFindingActions finding={finding({ can_apply: true })} onAct={onAct} />);

    screen.getByRole("button", { name: "Apply" }).click();

    expect(onAct).toHaveBeenCalledWith({ kind: "apply", findingId: "f1" });
  });
});

describe("which actions appear, and why", () => {
  it("offers Sign off on an AI judgment awaiting a signature", () => {
    // The act ADR-336's safety story rests on. Until LP-560 the only way to clear one of these was
    // Override, so every agreement was filed as a rejection.
    render(<RuleFindingActions finding={finding()} onAct={vi.fn()} />);

    expect(screen.getByRole("button", { name: "Sign off" })).toBeDefined();
  });

  it("does NOT offer Sign off on a deterministic verdict", () => {
    // Signing a verdict that was never a judgment records a review that did not happen.
    render(
      <RuleFindingActions
        finding={finding({ ratification_pending: false, evaluation_outcome: "open" })}
        onAct={vi.fn()}
      />,
    );

    expect(screen.queryByRole("button", { name: "Sign off" })).toBeNull();
  });

  it("does NOT offer Apply when the rule declares no change", () => {
    // Apply acts on the finding's declared change. A rule with none would give a button that looks
    // right and does nothing — worse than no button, because it reads as work completed.
    render(<RuleFindingActions finding={finding()} onAct={vi.fn()} />);

    expect(screen.queryByRole("button", { name: "Apply" })).toBeNull();
  });

  it("names the documents on the request button", () => {
    // The processor should not have to open the card to learn what is being asked for.
    render(
      <RuleFindingActions
        finding={finding({
          evaluation_outcome: "couldnt_check",
          missing_documents: ["credit report", "appraisal"],
        })}
        onAct={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: /credit report, appraisal/ })).toBeDefined();
  });

  it("shows nothing on a passing check", () => {
    // A control on every one of 28 satisfied rows is noise on exactly the lines a processor skips.
    const { container } = render(
      <RuleFindingActions
        finding={finding({ evaluation_outcome: "satisfied", ratification_pending: false })}
        onAct={vi.fn()}
      />,
    );

    expect(container.firstChild).toBeNull();
  });

  it("offers Undo once resolved, and nothing else", () => {
    // Undo is what makes the other actions safe to use: without it every click feels irreversible,
    // and hesitation is why findings sit untouched.
    render(
      <RuleFindingActions finding={finding({ resolution_status: "ratified" })} onAct={vi.fn()} />,
    );

    expect(screen.getByRole("button", { name: "Undo" })).toBeDefined();
    expect(screen.queryByRole("button", { name: "Sign off" })).toBeNull();
  });
});

describe("the reason is required where it carries the audit trail", () => {
  it('will not submit a "not an issue" dismissal without one', () => {
    // An override contradicts the engine, and the reason is what a later reader has instead of the
    // finding. Accept-risk and note are the same. A request needs none — the document names it.
    const onAct = vi.fn();
    render(<RuleFindingActions finding={finding()} onAct={onAct} />);

    // LP-584 — "Not an issue" states the claim; the wire action is still `override`.
    screen.getByRole("button", { name: "Not an issue" }).click();
    screen.getByRole("button", { name: "Not an issue" }).click();

    expect(onAct).not.toHaveBeenCalled();
  });
});
