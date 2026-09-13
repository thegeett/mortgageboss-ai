// @vitest-environment jsdom
/**
 * LP-855 Screen 10 — "Which mail app should this open?"
 *
 * THE SEED MOVES A RADIO BUTTON AND SAYS WHY. IT NEVER DECIDES. That is the property these are
 * about: a guess that applied itself would open the wrong compose window with nothing on screen
 * explaining it, and the processor would have to work out that we had chosen for them.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MailClientDialog } from "./mail-client-dialog";

afterEach(cleanup);

describe("MailClientDialog", () => {
  it("offers the safe answer alongside the two web clients", () => {
    render(<MailClientDialog open suggested="mailto" reason="" onChoose={vi.fn()} />);

    expect(screen.getByLabelText(/Gmail/)).toBeTruthy();
    expect(screen.getByLabelText(/Outlook on the web/)).toBeTruthy();
    expect(screen.getByLabelText(/Whatever this computer opens/)).toBeTruthy();
    expect(screen.getByText(/the safe answer if you're unsure/)).toBeTruthy();
  });

  it("pre-selects the suggestion and says WHY, on that option", () => {
    render(
      <MailClientDialog
        open
        suggested="gmail"
        reason="you sign in as priya@gmail.com"
        onChoose={vi.fn()}
      />,
    );

    expect((screen.getByLabelText(/Gmail/) as HTMLInputElement).checked).toBe(true);
    expect(screen.getByText(/suggested, because you sign in as priya@gmail.com/)).toBeTruthy();
  });

  it("does not DECIDE — the suggestion is only a selection until a button is pressed", () => {
    const onChoose = vi.fn();
    render(
      <MailClientDialog open suggested="gmail" reason="you sign in as x" onChoose={onChoose} />,
    );

    expect(onChoose).not.toHaveBeenCalled();
  });

  it("a processor can pick something else, and that is what is saved", () => {
    const onChoose = vi.fn();
    render(
      <MailClientDialog open suggested="gmail" reason="you sign in as x" onChoose={onChoose} />,
    );

    fireEvent.click(screen.getByLabelText(/Whatever this computer opens/));
    fireEvent.click(screen.getByRole("button", { name: /^Use my mail app$/ }));

    expect(onChoose).toHaveBeenCalledWith("mailto");
  });

  it("the primary's label follows the selection", () => {
    render(
      <MailClientDialog open suggested="gmail" reason="you sign in as x" onChoose={vi.fn()} />,
    );
    expect(screen.getByRole("button", { name: "Use Gmail" })).toBeTruthy();

    fireEvent.click(screen.getByLabelText(/Outlook on the web/));
    expect(screen.getByRole("button", { name: "Use Outlook" })).toBeTruthy();
  });

  it("'Not now' is an ANSWER — it stores the safe one", () => {
    // A dialog that could be dismissed without answering would come back on every draft, and a
    // processor who wanted the desktop default would have no way to say so.
    const onChoose = vi.fn();
    render(
      <MailClientDialog open suggested="gmail" reason="you sign in as x" onChoose={onChoose} />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Not now" }));

    expect(onChoose).toHaveBeenCalledWith("mailto");
  });

  it("says nothing about a suggestion it cannot justify", () => {
    // A processor at a mortgage company signs in as @theirfirm.com, which is consistent with every
    // client. "Suggested because we could not tell" is not a reason anybody benefits from reading.
    render(<MailClientDialog open suggested="mailto" reason="" onChoose={vi.fn()} />);

    expect(screen.queryByText(/suggested, because/)).toBeNull();
    expect(
      (screen.getByLabelText(/Whatever this computer opens/) as HTMLInputElement).checked,
    ).toBe(true);
  });

  it("renders nothing when it is not open", () => {
    render(<MailClientDialog open={false} suggested="gmail" reason="x" onChoose={vi.fn()} />);
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
