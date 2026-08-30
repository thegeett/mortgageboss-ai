// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { TooltipProvider } from "@/components/ui/tooltip";
import type { TierInput } from "@/lib/confidence";
import { ScrutinyMark } from "./scrutiny-mark";

afterEach(cleanup);

const ORDINARY: TierInput = { confidence: 0.99, critical: false, distrustedReason: null };

function renderMark(input: Partial<TierInput> = {}) {
  return render(
    <TooltipProvider>
      <ScrutinyMark input={{ ...ORDINARY, ...input }} />
    </TooltipProvider>,
  );
}

describe("ScrutinyMark", () => {
  it("renders NOTHING for a confident field", () => {
    // The ticket's first acceptance criterion, and the reason the others are
    // legible: a mark on every row is a mark on no row.
    const { container } = renderMark();
    expect(container.textContent).toBe("");
  });

  it("marks a critical field however sure the model is", () => {
    renderMark({ confidence: 1, critical: true });
    expect(screen.getByText("Check this")).toBeTruthy();
  });

  it("marks an unrated field without treating it as a warning", () => {
    renderMark({ confidence: null });
    expect(screen.getByText("Not rated")).toBeTruthy();
    // Neutral, not amber: three-quarters of fields carry no rating, and colouring
    // them all as problems would make the amber ones invisible.
    expect(screen.getByText("Not rated").className).toContain("text-muted-foreground");
  });

  it("marks a low-confidence ordinary field", () => {
    renderMark({ confidence: 0.4 });
    expect(screen.getByText("Check this").className).toContain("text-warning");
  });

  it("marks a known-bad extractor field even at full confidence", () => {
    renderMark({ confidence: 1, distrustedReason: "doc 146 — hallucinated licence values" });
    expect(screen.getByText("Check this")).toBeTruthy();
  });

  it("says 'check', never 'blocking' — the field is worth reading, not wrong", () => {
    renderMark({ confidence: 0.2, critical: true });
    const token = screen.getByText("Check this");
    expect(token.className).toContain("text-warning");
    expect(token.className).not.toContain("text-destructive");
  });

  it("is reachable by keyboard, because the reason is only in the hover", () => {
    renderMark({ confidence: null });
    // A real button rather than a span carrying a tabIndex: a tab stop on a
    // non-interactive element announces something focusable that answers nothing.
    const trigger = screen.getByText("Not rated").closest("button");
    expect(trigger).toBeTruthy();
    expect(trigger?.getAttribute("type")).toBe("button");
  });
});
