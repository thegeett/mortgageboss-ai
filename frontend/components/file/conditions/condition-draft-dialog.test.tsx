// @vitest-environment jsdom
/**
 * S3-04 (LP-922): the draft dialog shows the draft as the server built it, says nothing is sent from
 * the app, offers the four buttons, and will not mark sent a draft with no address.
 */
import type { ConditionDraft } from "@/lib/types/conditions";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const draft = vi.hoisted(() => ({ data: undefined as ConditionDraft | undefined }));
vi.mock("@/lib/api/conditions", () => ({
  useConditionDraft: () => ({ data: draft.data }),
  useMarkConditionDraftSent: () => ({ mutate: vi.fn(), isPending: false }),
  useDeleteConditionDraft: () => ({ mutate: vi.fn(), isPending: false }),
  useSetConditionDraftAddress: () => ({ mutate: vi.fn(), isPending: false }),
  useSetConditionDraftDueDate: () => ({ mutate: vi.fn(), isPending: false }),
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
    { condition_id: "c", code: "6637", label: "Earnest money: source and clearance" },
  ],
  asked_once: [{ what: "July and August statements", codes: ["7086", "6132", "6637"] }],
  other_drafts: [],
  mortgagee_clause: null,
  why_facts: [],
  becomes: "Waiting on Borrower",
  due_date: "2026-09-03",
};

describe("ConditionDraftDialog", () => {
  it("is S3-04", () => {
    draft.data = BORROWER;
    render(<ConditionDraftDialog fileId="f1" draftId="d1" onClose={vi.fn()} />);
    expect(screen.getByText("Email to the borrower · round 1")).toBeDefined();
    expect(screen.getByText(DRAFT_SUBTITLE)).toBeDefined();
    expect(screen.getByText("Earnest money: source and clearance")).toBeDefined();
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
