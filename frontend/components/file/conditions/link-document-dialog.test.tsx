// @vitest-environment jsdom
/**
 * LP-958 — the Link dialog: the server's matches first, the rest after, search, the mismatch warning
 * before she links a document that does not answer the item, and nothing she cannot link.
 */
import type { Condition, ConditionItem, LinkCandidate } from "@/lib/types/conditions";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const calls = vi.hoisted(() => ({ link: [] as unknown[] }));
const state = vi.hoisted(() => ({
  candidates: { isPending: false, isError: false, data: [] as unknown[] } as Record<
    string,
    unknown
  >,
}));
vi.mock("@/lib/api/conditions", () => ({
  useLinkItemDocument: () => ({ isPending: false, mutate: (b: unknown) => calls.link.push(b) }),
  useLinkCandidates: () => state.candidates,
}));

import { LinkDocumentDialog } from "./link-document-dialog";

afterEach(() => {
  cleanup();
  calls.link = [];
});

const CONDITION = { id: "c1", lender_code: "0006" } as Condition;
const ITEM = { id: "i1", name: "Credit report invoice" } as ConditionItem;

function doc(id: string, name: string, extra: Partial<LinkCandidate> = {}): LinkCandidate {
  return {
    document_id: id,
    name,
    type_label: "Service invoice",
    created_at: "2026-07-15T12:00:00Z",
    matches: false,
    linked: false,
    unlinked_by_her: false,
    ...extra,
  };
}

/** The server's order: the match first, then newest first. */
const FILE_DOCS = [
  doc("inv", "Credit report invoice", { matches: true }),
  doc("report", "Credit report", { type_label: "Credit report" }),
  doc("proc", "Processing invoice"),
  doc("done", "Already linked invoice", { matches: true, linked: true }),
];

function open(extra: { replaceDocumentId?: string } = {}) {
  state.candidates = { isPending: false, isError: false, data: FILE_DOCS };
  render(
    <LinkDocumentDialog
      open
      onOpenChange={vi.fn()}
      fileId="f1"
      condition={CONDITION}
      item={ITEM}
      {...extra}
    />,
  );
  return screen.getByRole("dialog");
}

describe("LinkDocumentDialog", () => {
  it("lists the server's matches first, then the others, and never one already linked", () => {
    const dialog = open();
    const groups = within(dialog).getAllByText(/^(Matches this item|Other documents)$/);
    expect(groups.map((g) => g.textContent)).toEqual(["Matches this item", "Other documents"]);
    const radios = within(dialog)
      .getAllByRole("radio")
      .map((r) => r.closest("label")?.querySelector("span span")?.textContent);
    expect(radios).toEqual(["Credit report invoice", "Credit report", "Processing invoice"]);
  });

  it("names the group plainly when nothing matches", () => {
    state.candidates = {
      isPending: false,
      isError: false,
      data: [doc("report", "Credit report", { type_label: "Credit report" })],
    };
    render(
      <LinkDocumentDialog
        open
        onOpenChange={vi.fn()}
        fileId="f1"
        condition={CONDITION}
        item={ITEM}
      />,
    );
    expect(screen.queryByText("Matches this item")).toBeNull();
    expect(screen.queryByText("Other documents")).toBeNull();
    expect(screen.getByText("Documents on this file")).toBeTruthy();
  });

  it("warns before linking a document that does not answer the item, and not for a match", () => {
    const dialog = open();
    fireEvent.click(within(dialog).getByRole("radio", { name: /Credit report invoice/ }));
    expect(within(dialog).queryByText(/stays open until you accept it anyway/)).toBeNull();
    fireEvent.click(within(dialog).getAllByRole("radio")[1] as HTMLElement);
    expect(within(dialog).getByText(/stays open until you accept it anyway/)).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Link document" }));
    // Linking it is still hers to do: the server links it and its type check fails.
    expect(calls.link).toEqual([
      {
        conditionId: "c1",
        itemId: "i1",
        document_id: "report",
        page: null,
        replace_document_id: null,
      },
    ]);
  });

  it("searches the name and the type", () => {
    const dialog = open();
    fireEvent.change(within(dialog).getByLabelText("Search this file’s documents"), {
      target: { value: "processing" },
    });
    expect(within(dialog).getAllByRole("radio")).toHaveLength(1);
    fireEvent.change(within(dialog).getByLabelText("Search this file’s documents"), {
      target: { value: "credit report" },
    });
    expect(within(dialog).getAllByRole("radio")).toHaveLength(2);
    fireEvent.change(within(dialog).getByLabelText("Search this file’s documents"), {
      target: { value: "nothing like it" },
    });
    expect(within(dialog).getByText("No document on this file matches that search.")).toBeTruthy();
  });

  it("links nothing until a document is chosen", () => {
    const dialog = open();
    const button = within(dialog).getByRole("button", { name: "Link document" });
    expect((button as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(button);
    expect(calls.link).toEqual([]);
  });

  it("says when she unlinked this one from this item before", () => {
    state.candidates = {
      isPending: false,
      isError: false,
      data: [doc("inv", "Credit report invoice", { unlinked_by_her: true })],
    };
    render(
      <LinkDocumentDialog
        open
        onOpenChange={vi.fn()}
        fileId="f1"
        condition={CONDITION}
        item={ITEM}
      />,
    );
    fireEvent.click(screen.getByRole("radio"));
    expect(screen.getByText(/You unlinked this document from this item before/)).toBeTruthy();
  });

  it("each document has an Open link to it on this file", () => {
    const dialog = open();
    const links = within(dialog).getAllByRole("link", { name: "Open" });
    expect(links[0]?.getAttribute("href")).toBe("/loan-files/f1/documents?doc=inv");
  });
});
