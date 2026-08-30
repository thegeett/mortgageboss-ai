// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Aggression } from "@/lib/types/verification";
import { ThoroughnessControl } from "./thoroughness-control";

afterEach(cleanup);

const AGGRESSION: Aggression = {
  level: "balanced",
  default: "balanced",
  override: null,
  cutoff: 0.5,
  cutoffs: { conservative: 0.8, balanced: 0.5, thorough: 0 },
};

function renderControl(props: Partial<Parameters<typeof ThoroughnessControl>[0]> = {}) {
  const onPick = vi.fn();
  render(
    <ThoroughnessControl
      aggression={AGGRESSION}
      activeLevel="balanced"
      shownAt={(level) => ({ conservative: 3, balanced: 6, thorough: 9 })[level]}
      onPick={onPick}
      busy={false}
      {...props}
    />,
  );
  return onPick;
}

/** Render and open the menu. Radix hides the rest of the tree once it is open,
 *  so anything about the TRIGGER has to be asserted before this. */
function open(props: Partial<Parameters<typeof ThoroughnessControl>[0]> = {}) {
  const onPick = renderControl(props);
  fireEvent.pointerDown(
    screen.getByRole("button", { name: /Thoroughness/ }),
    new PointerEvent("pointerdown", { ctrlKey: false, button: 0 }),
  );
  return onPick;
}

/**
 * The dial, in the header (LP-UI-046).
 *
 * It existed only inside the Old findings tab — the one tab a processor has no
 * reason to open — and sat ~1,400px down the page. A control nobody finds is a
 * control that does not exist.
 */
describe("ThoroughnessControl", () => {
  it("names the active level on the trigger", () => {
    renderControl();
    // Asserted on the text rather than the accessible name: JSX renders
    // "Thoroughness: " and the label as separate nodes, so the computed name has
    // no space between them and a `name:` matcher reads as a failure of the
    // label rather than of the whitespace.
    const trigger = screen.getByRole("button", { name: /Thoroughness/ });
    expect(trigger.textContent).toContain("Balanced");
  });

  it("shows each level's threshold AND what it costs", () => {
    // A cutoff with no count is a setting whose effect you discover by choosing
    // it. The mockup pairs them for that reason.
    open();
    expect(screen.getByText(/≥ 80% confidence · 3 shown/)).toBeTruthy();
    expect(screen.getByText(/≥ 50% confidence · 6 shown/)).toBeTruthy();
  });

  it("says 'every finding' rather than '≥ 0% confidence'", () => {
    open();
    expect(screen.getByText(/every finding · 9 shown/)).toBeTruthy();
  });

  it("picks a level", () => {
    const onPick = open();
    fireEvent.click(screen.getByText("Thorough"));
    expect(onPick).toHaveBeenCalledWith("thorough");
  });

  it("SAYS WHAT IT FILTERS, and what it does not", () => {
    // A header control implies it governs the page. It governs the AI sweep: the
    // governed engine's low-confidence findings are `needs_review`, and hiding
    // those at a default setting would suppress exactly what needs a person.
    open();
    const note = screen.getByText(/Re-filters the AI cross-source findings/);
    expect(note.textContent).toMatch(/never re-runs anything/);
    expect(note.textContent).toMatch(/never hides a rule finding/);
  });

  it("is disabled while a change is in flight", () => {
    render(
      <ThoroughnessControl
        aggression={AGGRESSION}
        activeLevel="balanced"
        shownAt={() => 0}
        onPick={vi.fn()}
        busy
      />,
    );
    expect(screen.getByRole("button", { name: /Thoroughness/ }).hasAttribute("disabled")).toBe(
      true,
    );
  });
});
