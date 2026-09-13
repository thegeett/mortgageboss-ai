// @vitest-environment jsdom
/**
 * LP-851 — one dialog, three doors. Screens 3, 4 and 5.
 *
 * THE COUNT IS THE ASSERTION, not "a dialog appeared". "Never two dialogs in sequence" is invisible
 * to the obvious test: `getByRole("dialog")` passes for one dialog and for the first of two, and the
 * second one only arrives after the first is answered. Every case here counts.
 */
import type { DraftConflict } from "@/lib/api/draft-conflict";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { OpenDraftDialog } from "./open-draft-dialog";

afterEach(cleanup);

function need(id: string, title: string) {
  return { id, title };
}

function conflict(over: Partial<DraftConflict> = {}): DraftConflict {
  return {
    message: "There is already an open draft to the borrower.",
    decisions_required: [
      {
        party: "borrower",
        open_draft: {
          id: "d1",
          created_at: "2026-09-08T14:02:00Z",
          needs: [need("n1", "Bank statement — March"), need("n2", "Pay stub")],
          body_edited: false,
          edited_excerpt: null,
        },
        adding: [need("n3", "Homeowner's insurance declaration")],
      },
    ],
    would_create: [],
    ...over,
  };
}

describe("Screen 3 — adding to an open draft", () => {
  it("names the draft by its CONTENTS, not by an id", () => {
    // "There is an open draft" is not something a processor can decide with; three document names
    // and a timestamp are, and they are what they remember.
    render(<OpenDraftDialog conflict={conflict()} onCancel={vi.fn()} onChoose={vi.fn()} />);

    expect(screen.getByText(/There is already an open draft to the borrower/)).toBeTruthy();
    expect(screen.getByText("Bank statement — March")).toBeTruthy();
    expect(screen.getByText("Pay stub")).toBeTruthy();
    // The id is NOT how a draft is named here.
    expect(screen.queryByText(/d1/)).toBeNull();
  });

  it("offers three buttons and no fourth door", () => {
    // "Create a second open draft" is the option that is missing, and its absence is LP-850.
    render(<OpenDraftDialog conflict={conflict()} onCancel={vi.fn()} onChoose={vi.fn()} />);

    expect(screen.getByRole("button", { name: "Cancel" })).toBeTruthy();
    expect(
      screen.getByRole("button", { name: /I've sent it — mark sent, start new/ }),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "Add to the open draft" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /start a second draft/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /^create/i })).toBeNull();
  });

  it("says “I've sent it” rather than “Mark as sent”", () => {
    // Nothing observed a send. A neutral label invites pressing it to dismiss the dialog, which is
    // how `requested_at` ends up stamped on a message that never went out.
    render(<OpenDraftDialog conflict={conflict()} onCancel={vi.fn()} onChoose={vi.fn()} />);

    expect(screen.queryByRole("button", { name: /^Mark as sent$/ })).toBeNull();
  });

  it("sends back exactly one choice per button", () => {
    const onChoose = vi.fn();
    render(<OpenDraftDialog conflict={conflict()} onCancel={vi.fn()} onChoose={onChoose} />);

    fireEvent.click(screen.getByRole("button", { name: "Add to the open draft" }));
    expect(onChoose).toHaveBeenCalledWith("append");

    fireEvent.click(screen.getByRole("button", { name: /I've sent it/ }));
    expect(onChoose).toHaveBeenCalledWith("mark_sent_and_new");
  });

  it("Cancel chooses nothing", () => {
    // THE CONTROL on the decision. A Cancel that still answered would be the worst of both: a
    // processor told they had a choice, and the draft changed anyway.
    const onChoose = vi.fn();
    const onCancel = vi.fn();
    render(<OpenDraftDialog conflict={conflict()} onCancel={onCancel} onChoose={onChoose} />);

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onChoose).not.toHaveBeenCalled();
  });
});

describe("Screen 4 — one request, two parties", () => {
  const twoParties = conflict({
    would_create: [
      {
        party: "title",
        address: "closings@acmetitle.example",
        needs: [need("n4", "Title commitment")],
      },
    ],
  });

  it("is ONE dialog, not two", () => {
    // The rule this ticket exists for. A processor who has just confirmed five documents and is
    // then asked a second question clicks the primary without reading it.
    render(<OpenDraftDialog conflict={twoParties} onCancel={vi.fn()} onChoose={vi.fn()} />);

    expect(screen.getAllByRole("dialog")).toHaveLength(1);
  });

  it("shows the party that needs NO decision, with no buttons", () => {
    // LP-852's rule appearing here. A test that only checked the conflicting party's row passes on
    // a build where the no-decision parties were silently dropped — which is a draft to the title
    // company that nobody notices, and therefore never sends.
    render(<OpenDraftDialog conflict={twoParties} onCancel={vi.fn()} onChoose={vi.fn()} />);

    expect(screen.getByText(/title company · a new draft/i)).toBeTruthy();
    // The chip prefixes the name with "+ ", so the match is on the name within it.
    expect(screen.getByText(/Title commitment/)).toBeTruthy();
    expect(screen.getByText(/this creates a draft to closings@acmetitle.example/)).toBeTruthy();
  });

  it("gives the party that DOES need a decision its own two buttons", () => {
    render(<OpenDraftDialog conflict={twoParties} onCancel={vi.fn()} onChoose={vi.fn()} />);

    expect(screen.getByRole("button", { name: "Mark sent, start new" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Add to it" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Do both" })).toBeTruthy();
  });

  it("says a party has no address rather than pretending it has one", () => {
    render(
      <OpenDraftDialog
        conflict={conflict({
          would_create: [
            { party: "title", address: null, needs: [need("n4", "Title commitment")] },
          ],
        })}
        onCancel={vi.fn()}
        onChoose={vi.fn()}
      />,
    );

    expect(screen.getByText(/no address on file yet/)).toBeTruthy();
  });
});

describe("Screen 5 — the draft has the processor's words in it", () => {
  /** An open draft a processor has written into, with whatever they wrote. */
  function editedBy(excerpt: string | null): DraftConflict {
    return conflict({
      decisions_required: [
        {
          party: "borrower",
          open_draft: {
            id: "d1",
            created_at: "2026-09-08T14:02:00Z",
            needs: [need("n1", "Bank statement — March")],
            body_edited: true,
            edited_excerpt: excerpt,
          },
          adding: [need("n3", "Homeowner's insurance declaration")],
        },
      ],
    });
  }

  const edited = editedBy("March statement only, not February");

  it("quotes the processor's own line back at them", () => {
    // "Your changes will be lost" is abstract and gets dismissed; their own sentence does not.
    render(<OpenDraftDialog conflict={edited} onCancel={vi.fn()} onChoose={vi.fn()} />);

    expect(screen.getByText("You have edited this draft.")).toBeTruthy();
    expect(screen.getByText(/March statement only, not February/)).toBeTruthy();
  });

  it("renders the quote as TEXT, never as markup", () => {
    // The column guarantee covers the column. This fragment is lifted OUT of it into a different
    // field, so it inherits nothing and has to be escaped where it lands.
    render(
      <OpenDraftDialog
        conflict={editedBy("<img src=x onerror=alert(1)>bold</b>")}
        onCancel={vi.fn()}
        onChoose={vi.fn()}
      />,
    );

    expect(document.querySelector("img")).toBeNull();
    // It is visible as the characters the processor typed.
    expect(screen.getByText(/<img src=x onerror=alert\(1\)>bold<\/b>/)).toBeTruthy();
  });

  it("makes the primary read “Add anyway”", () => {
    render(<OpenDraftDialog conflict={edited} onCancel={vi.fn()} onChoose={vi.fn()} />);

    expect(screen.getByRole("button", { name: "Add anyway" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Add to the open draft" })).toBeNull();
  });

  it("drops the quotation rather than inventing one when there is nothing to quote", () => {
    render(<OpenDraftDialog conflict={editedBy(null)} onCancel={vi.fn()} onChoose={vi.fn()} />);

    expect(screen.getByText("You have edited this draft.")).toBeTruthy();
    expect(screen.queryByText(/including/)).toBeNull();
  });

  it("shows no warning at all on a draft nobody has edited", () => {
    // THE CONTROL. A dialog that warned every time would teach a processor to click past it, which
    // is the one failure mode a warning cannot survive.
    render(<OpenDraftDialog conflict={conflict()} onCancel={vi.fn()} onChoose={vi.fn()} />);

    expect(screen.queryByText("You have edited this draft.")).toBeNull();
  });
});

describe("nothing to decide", () => {
  it("renders no dialog", () => {
    // Acceptance 1: requesting with no open draft shows NO dialog. Asserted on the component so the
    // empty case is a state rather than an accident of where it is mounted.
    render(<OpenDraftDialog conflict={null} onCancel={vi.fn()} onChoose={vi.fn()} />);

    expect(screen.queryAllByRole("dialog")).toHaveLength(0);
  });
});
