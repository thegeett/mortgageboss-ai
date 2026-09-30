// @vitest-environment jsdom
/**
 * S3-04 (LP-922): the draft dialog shows the draft as the server built it, says nothing is sent from
 * the app, offers the four buttons, and will not mark sent a draft with no address.
 */
import type { ConditionDraft, DraftPolish } from "@/lib/types/conditions";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const draft = vi.hoisted(() => ({ data: undefined as ConditionDraft | undefined }));
const polish = vi.hoisted(() => ({
  result: null as DraftPolish | null,
  applied: [] as { body_html: string; warnings_accepted: number }[],
}));
vi.mock("@/lib/api/conditions", () => ({
  useConditionDraft: () => ({ data: draft.data }),
  useMarkConditionDraftSent: () => ({ mutate: vi.fn(), isPending: false }),
  useDeleteConditionDraft: () => ({ mutate: vi.fn(), isPending: false }),
  useSetConditionDraftAddress: () => ({ mutate: vi.fn(), isPending: false }),
  useSetConditionDraftDueDate: () => ({ mutate: vi.fn(), isPending: false }),
  // "Polish with AI": answers with whatever the test put in `polish.result`.
  usePolishConditionDraft: () => ({
    isPending: false,
    mutate: (_: unknown, options: { onSuccess: (result: DraftPolish) => void }) => {
      if (polish.result) options.onSuccess(polish.result);
    },
  }),
  useApplyPolish: () => ({
    isPending: false,
    mutate: (body: { body_html: string; warnings_accepted: number }) => polish.applied.push(body),
  }),
}));
vi.mock("@/lib/api/preferences", () => ({
  usePreferences: () => ({ data: { mail_client: "gmail", suggested_mail_client: "gmail" } }),
  useUpdatePreferences: () => ({ mutate: vi.fn(), isPending: false }),
}));

import { ConditionDraftDialog, DRAFT_SUBTITLE } from "./condition-draft-dialog";

afterEach(cleanup);

const BORROWER: ConditionDraft = {
  id: "d1",
  communication_id: "c1",
  recipient: "borrower",
  round_number: 1,
  title: "Email to the borrower · round 1",
  status: "draft",
  sent_at: null,
  to: "Alex Rivera <alex.rivera@example.com>",
  needs_address: false,
  subject: "Documents needed for your loan — 2 items",
  body_html:
    "<p>Hi Alex,</p><ol><li><strong>Your Capital One statements ending 9912</strong></li></ol>",
  in_this_email: [
    { condition_id: "a", code: "7086", label: "More assets for closing" },
    { condition_id: "b", code: "6132", label: "One more consecutive month" },
    {
      condition_id: "c",
      code: "6637",
      label: "Earnest money: source of the earnest money and clearance",
    },
  ],
  asked_once: [{ what: "July and August statements", codes: ["7086", "6132", "6637"] }],
  other_drafts: [],
  mortgagee_clause: null,
  why_facts: [],
  becomes: "Waiting on Borrower",
  due_date: "2026-09-03",
  polished_at: null,
};

describe("ConditionDraftDialog", () => {
  it("is S3-04", () => {
    draft.data = BORROWER;
    render(<ConditionDraftDialog fileId="f1" draftId="d1" onClose={vi.fn()} />);
    expect(screen.getByText("Email to the borrower · round 1")).toBeDefined();
    expect(screen.getByText(DRAFT_SUBTITLE)).toBeDefined();
    expect(
      screen.getByText("Earnest money: source of the earnest money and clearance"),
    ).toBeDefined();
    expect(screen.getByText("7086, 6132 and 6637")).toBeDefined();
    expect(screen.getByText(/Account shown as last four only/)).toBeDefined();
    expect(screen.getByText("Alex Rivera <alex.rivera@example.com>")).toBeDefined();
    expect((screen.getByLabelText("Due date") as HTMLInputElement).value).toBe("2026-09-03");
    for (const name of ["Copy & open Gmail", "Copy message", "Mark as sent", "Delete draft"]) {
      expect(screen.getByRole("button", { name })).toBeDefined();
    }
  });

  it("asks for a missing address and will not mark the draft sent without one", () => {
    draft.data = { ...BORROWER, to: "", needs_address: true };
    render(<ConditionDraftDialog fileId="f1" draftId="d1" onClose={vi.fn()} />);
    expect(screen.getByLabelText("Email address")).toBeDefined();
    const mark = screen.getByRole("button", { name: "Mark as sent" }) as HTMLButtonElement;
    expect(mark.disabled).toBe(true);
  });

  it("a sent draft offers no send, copy or delete", () => {
    draft.data = { ...BORROWER, status: "sent", sent_at: "2026-08-28T21:02:00Z" };
    render(<ConditionDraftDialog fileId="f1" draftId="d1" onClose={vi.fn()} />);
    expect(screen.queryByRole("button", { name: "Mark as sent" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Delete draft" })).toBeNull();
    expect(screen.getByText(/Marked sent/)).toBeDefined();
  });
});

describe("Polish with AI (LP-922 follow-up)", () => {
  it("shows the proposal with the facts it changed, and stores nothing until Use this", () => {
    draft.data = BORROWER;
    polish.applied = [];
    polish.result = {
      polished_html: "<p>Hello Alex,</p><ol><li>statements</li></ol>",
      warnings: [{ kind: "dropped", fact: "$38,210.40", sentence: "Dropped: $38,210.40" }],
      refusal: null,
    };
    render(<ConditionDraftDialog fileId="f1" draftId="d1" onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Polish with AI" }));
    expect(screen.getByText(/Proposed by AI/)).toBeDefined();
    expect(screen.getByText("Dropped: $38,210.40")).toBeDefined();
    expect(screen.getByText("Hello Alex,")).toBeDefined();
    // The send buttons wait until she decides.
    expect(screen.queryByRole("button", { name: "Mark as sent" })).toBeNull();
    expect(polish.applied).toEqual([]);
    fireEvent.click(screen.getByRole("button", { name: "Use this" }));
    expect(polish.applied).toEqual([
      {
        draftId: "d1",
        body_html: "<p>Hello Alex,</p><ol><li>statements</li></ol>",
        warnings_accepted: 1,
      },
    ]);
  });

  it("Keep mine puts her draft back", () => {
    draft.data = BORROWER;
    polish.result = { polished_html: "<p>Hello Alex,</p>", warnings: [], refusal: null };
    render(<ConditionDraftDialog fileId="f1" draftId="d1" onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Polish with AI" }));
    expect(screen.getByText(/checked by code/)).toBeDefined();
    fireEvent.click(screen.getByRole("button", { name: "Keep mine" }));
    expect(screen.queryByText(/Proposed by AI/)).toBeNull();
    expect(screen.getByRole("button", { name: "Mark as sent" })).toBeDefined();
  });

  it("says so when there is no proposal", () => {
    draft.data = BORROWER;
    polish.result = {
      polished_html: null,
      warnings: [],
      refusal: "The AI could not polish this email just now.",
    };
    render(<ConditionDraftDialog fileId="f1" draftId="d1" onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Polish with AI" }));
    expect(screen.getByText("The AI could not polish this email just now.")).toBeDefined();
  });

  it("marks a polished draft as the AI's", () => {
    draft.data = { ...BORROWER, polished_at: "2026-08-28T20:45:00Z" };
    render(<ConditionDraftDialog fileId="f1" draftId="d1" onClose={vi.fn()} />);
    expect(screen.getByText(/Polished by AI/)).toBeDefined();
  });
});
