// @vitest-environment jsdom
/**
 * LP-969 review — the blocks' mapping is what decides what the server does, and it had no test of its
 * own: the panel tests drive the component but never pin which performers and which option each block
 * emits. These are the three properties the rest of the review leans on.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
// LP-971 — the open menu now holds "Describe it", which calls the API; these tests do not.
vi.mock("@/lib/api/conditions", () => ({
  useDescribeSteps: () => ({ mutate: vi.fn(), isPending: false }),
}));

import { AddStep, EMAIL_WHO } from "./plan-add-step";

afterEach(cleanup);

function open(onAdd: (step: unknown) => void) {
  render(<AddStep conditionId="c1" ownStep={null} pending={false} onAdd={onAdd} />);
  fireEvent.click(screen.getByRole("button", { name: "Add a step" }));
}

function fill(label: string, words: string) {
  fireEvent.click(screen.getByRole("button", { name: new RegExp(label) }));
  fireEvent.change(screen.getByRole("textbox"), { target: { value: words } });
  fireEvent.click(screen.getByRole("button", { name: "Add the step" }));
}

describe("AddStep", () => {
  it("offers one email destination per real recipient, and not two for one (LP-969 review)", () => {
    // `condition_plan._RECIPIENT` maps BOTH `title` and `attorney` to the single `title_attorney`
    // email, so offering both put two labels on one draft — picking either produced the same email.
    // `item-links.tsx`'s ASK_WHO already excludes it (LP-955 review), and two lists answering "who can
    // I ask?" differently is what invites the next divergence.
    expect(EMAIL_WHO).not.toContain("attorney");
    expect(EMAIL_WHO).toContain("title");
    // Herself is a to-do, and an appraiser's ask goes through the lender (LP-942).
    expect(EMAIL_WHO).not.toContain("processor");
    expect(EMAIL_WHO).not.toContain("appraiser");
    // THE CONTROL: the lender IS offered, which is the deliberate difference from ASK_WHO — a free
    // email to the lender is something she sends; delegating a task to the lender is not.
    expect(EMAIL_WHO).toContain("lender");
    expect(EMAIL_WHO).toContain("borrower");
  });

  it("no block's hint tells her to do something she may already have done (LP-969 review)", () => {
    // "Ask the borrower to upload" read "…with a secure upload link once you confirm the plan", and
    // adding a step to an ALREADY-confirmed round is a normal flow since LP-968 — the link then exists
    // at once. The path's own send step carries the confirm nuance; a hint that describes one state is
    // wrong in the other, so no hint should name confirming at all.
    render(<AddStep conditionId="c1" ownStep={null} pending={false} onAdd={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Add a step" }));
    const hints = screen.getAllByRole("listitem").map((li) => li.textContent ?? "");
    expect(hints.length).toBeGreaterThan(4);
    for (const hint of hints) expect(hint).not.toMatch(/confirm/i);
    // THE CONTROL: the upload block is one of them, and still promises the link.
    expect(hints.some((h) => /secure upload link/.test(h))).toBe(true);
  });

  it("a step that opens the document picker asks exactly one person (LP-969 review)", () => {
    // THE PREMISE THE PANEL'S "CHECK A DOCUMENT" RESTS ON. It finds the item it just created as the
    // one whose id was not there before, and `condition_plan.add_item` calls `split_item` — so a link
    // step with two performers would create a base item AND parts, and the panel would open the
    // picker on whichever the response listed first. One performer cannot split.
    const added = vi.fn();
    open(added);
    fill("Check a document on the file", "the HOA certificate");
    expect(added).toHaveBeenCalledTimes(1);
    const step = added.mock.calls[0]?.[0] as { link?: boolean; performers: string[]; name: string };
    expect(step.link).toBe(true);
    expect(step.performers).toHaveLength(1);
    expect(step.performers[0]).toBe("processor");
    expect(step.name).toBe("Check the HOA certificate");
  });

  it("emails the borrower as the borrower's ask and anyone else as a third party", () => {
    // The same mapping `item-links.tsx` uses, and the one `recipient_for` reads to pick the email.
    // The default is the borrower, so this is the mapping's first branch without touching the select.
    const added = vi.fn();
    open(added);
    fireEvent.click(screen.getByRole("button", { name: /Email someone/ }));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "two statements" } });
    fireEvent.click(screen.getByRole("button", { name: "Add the step" }));
    expect(added.mock.calls[0]?.[0]).toMatchObject({
      option: "ask_borrower",
      performers: ["borrower"],
    });

    // THE OTHER BRANCH: anyone else is a third-party ask, which is what `recipient_for` reads to pick
    // the email — and the same mapping `item-links.tsx` uses.
    cleanup();
    const second = vi.fn();
    open(second);
    fireEvent.click(screen.getByRole("button", { name: /Email someone/ }));
    fireEvent.change(screen.getByLabelText("To"), { target: { value: "title" } });
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "the payoff" } });
    fireEvent.click(screen.getByRole("button", { name: "Add the step" }));
    expect(second.mock.calls[0]?.[0]).toMatchObject({
      option: "ask_third_party",
      performers: ["title"],
    });
  });
});
