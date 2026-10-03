// @vitest-environment jsdom
/**
 * LP-953, redrawn by LP-958 — her actions on an item: Add document ▾ (Link a document on this file…,
 * which opens the Link dialog, and Upload a new document…), Ask someone ▾, and Change.
 */
import type { Condition, ConditionItem, LinkCandidate } from "@/lib/types/conditions";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const calls = vi.hoisted(() => ({
  link: [] as unknown[],
  upload: [] as unknown[],
  update: [] as unknown[],
}));
const candidates = vi.hoisted(() => ({ data: [] as LinkCandidate[] }));
vi.mock("@/lib/api/conditions", () => ({
  useLinkItemDocument: () => ({ isPending: false, mutate: (b: unknown) => calls.link.push(b) }),
  useUploadToItem: () => ({ isPending: false, mutate: (b: unknown) => calls.upload.push(b) }),
  useUpdateItem: () => ({ isPending: false, mutate: (b: unknown) => calls.update.push(b) }),
  useLinkCandidates: () => ({ isPending: false, isError: false, data: candidates.data }),
}));

import { ItemLinkActions } from "./item-links";

afterEach(() => {
  cleanup();
  calls.link = [];
  calls.upload = [];
  calls.update = [];
});

const CONDITION = { id: "c1", lender_code: "0006" } as Condition;
const ITEM = {
  id: "i1",
  name: "Credit report invoice",
  option: "i_will_do_it",
} as ConditionItem;

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

candidates.data = [
  doc("d1", "Credit report invoice", { matches: true }),
  doc("d2", "Credit report", { type_label: "Credit report" }),
];

function openMenu(label: string) {
  fireEvent.click(screen.getByRole("button", { name: label }));
  return screen.getByRole("menu", { name: label });
}

describe("ItemLinkActions", () => {
  it("Add document ▾ offers Link and Upload; Link opens the dialog and links with its page", () => {
    render(<ItemLinkActions fileId="f1" condition={CONDITION} item={ITEM} />);
    const menu = openMenu("Add document");
    expect(
      within(menu)
        .getAllByRole("menuitem")
        .map((m) => m.textContent),
    ).toEqual(["Link a document on this file…", "Upload a new document…"]);
    fireEvent.click(within(menu).getByRole("menuitem", { name: /Link a document/ }));
    const dialog = screen.getByRole("dialog", { name: "Link a document to 0006" });
    fireEvent.click(within(dialog).getByRole("radio", { name: /Credit report invoice/ }));
    fireEvent.change(within(dialog).getByLabelText("Page (optional)"), { target: { value: "2" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Link document" }));
    expect(calls.link).toEqual([
      { conditionId: "c1", itemId: "i1", document_id: "d1", page: 2, replace_document_id: null },
    ]);
  });

  it("changes a link: the dialog opens at once, without the old document, and sends it replaced", () => {
    render(
      <ItemLinkActions fileId="f1" condition={CONDITION} item={ITEM} replaceDocumentId="d2" />,
    );
    const dialog = screen.getByRole("dialog", { name: "Change the document for 0006" });
    expect(within(dialog).getAllByRole("radio")).toHaveLength(1);
    fireEvent.click(within(dialog).getByRole("radio", { name: /Credit report invoice/ }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Use this document" }));
    expect(calls.link).toEqual([
      { conditionId: "c1", itemId: "i1", document_id: "d1", page: null, replace_document_id: "d2" },
    ]);
    // No menus in the Change form: the card already has its own controls. `hidden: true` because
    // the open dialog hides everything behind it from the accessibility tree, which would make a
    // plain query pass whether the menus rendered or not.
    expect(screen.queryByRole("button", { name: "Add document", hidden: true })).toBeNull();
  });

  it("uploads here, linked to this item", () => {
    render(<ItemLinkActions fileId="f1" condition={CONDITION} item={ITEM} />);
    const file = new File(["%PDF"], "invoice.pdf", { type: "application/pdf" });
    fireEvent.change(screen.getByLabelText("Upload a document for Credit report invoice"), {
      target: { files: [file] },
    });
    expect(calls.upload).toEqual([{ conditionId: "c1", itemId: "i1", files: [file] }]);
  });

  it("asks someone for her task: the LO gets it as an ask (LP-955)", () => {
    render(<ItemLinkActions fileId="f1" condition={CONDITION} item={ITEM} />);
    const menu = openMenu("Ask someone");
    fireEvent.click(within(menu).getByRole("menuitem", { name: "The LO" }));
    expect(calls.update).toEqual([
      { conditionId: "c1", itemId: "i1", option: "ask_third_party", performers: ["lo"] },
    ]);
    // The menu closes on a choice.
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("keeps the keyboard the native select had: arrows move, Escape returns focus (LP-958 review)", () => {
    // This menu REPLACED a `<select>`, which had arrow keys, Home/End and focus management for free,
    // and it declares `role="menu"` — a promise to a screen reader that those keys work. Without the
    // focus return, a keyboard user is dropped at the top of the drawer after every choice.
    render(<ItemLinkActions fileId="f1" condition={CONDITION} item={ITEM} />);
    const trigger = screen.getByRole("button", { name: "Ask someone" });
    const menu = openMenu("Ask someone");
    const choices = within(menu).getAllByRole("menuitem");
    expect(choices.length).toBeGreaterThan(2);
    expect(document.activeElement).toBe(choices[0]);
    fireEvent.keyDown(menu, { key: "ArrowDown" });
    expect(document.activeElement).toBe(choices[1]);
    fireEvent.keyDown(menu, { key: "ArrowUp" });
    expect(document.activeElement).toBe(choices[0]);
    fireEvent.keyDown(menu, { key: "ArrowUp" });
    expect(document.activeElement).toBe(choices[choices.length - 1]);
    fireEvent.keyDown(menu, { key: "Home" });
    expect(document.activeElement).toBe(choices[0]);
    fireEvent.keyDown(menu, { key: "End" });
    expect(document.activeElement).toBe(choices[choices.length - 1]);
    fireEvent.keyDown(menu, { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it("offers every recipient an ask reaches, and routes the insurance agent to their own email", () => {
    // LP-955 REVIEW: four of the seven were offered, so the insurance, HOA and employer emails were
    // unreachable from the only door that delegates her task — and an insurance ask sent as "Someone
    // else" lands in the other-party draft without the mortgagee clause the insurance email carries.
    render(<ItemLinkActions fileId="f1" condition={CONDITION} item={ITEM} />);
    const menu = openMenu("Ask someone");
    expect(
      within(menu)
        .getAllByRole("menuitem")
        .map((m) => m.textContent),
    ).toEqual([
      "The LO",
      "The borrower",
      "Title",
      "The insurance agent",
      "The HOA",
      "The employer",
      "Someone else",
    ]);
    fireEvent.click(within(menu).getByRole("menuitem", { name: "The insurance agent" }));
    expect(calls.update).toEqual([
      { conditionId: "c1", itemId: "i1", option: "ask_third_party", performers: ["insurance"] },
    ]);
  });

  it("asks the borrower as the borrower's ask, and is not offered on an ask", () => {
    const { unmount } = render(<ItemLinkActions fileId="f1" condition={CONDITION} item={ITEM} />);
    fireEvent.click(
      within(openMenu("Ask someone")).getByRole("menuitem", { name: "The borrower" }),
    );
    expect(calls.update).toEqual([
      { conditionId: "c1", itemId: "i1", option: "ask_borrower", performers: ["borrower"] },
    ]);
    unmount();
    const asked = { ...ITEM, option: "ask_third_party" } as ConditionItem;
    render(<ItemLinkActions fileId="f1" condition={CONDITION} item={asked} />);
    expect(screen.queryByRole("button", { name: "Ask someone" })).toBeNull();
    expect(screen.getByRole("button", { name: "Add document" })).toBeTruthy();
  });

  it("Escape closes a menu without closing what it sits in", () => {
    render(<ItemLinkActions fileId="f1" condition={CONDITION} item={ITEM} />);
    openMenu("Add document");
    const outer = vi.fn();
    document.addEventListener("keydown", outer);
    fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
    document.removeEventListener("keydown", outer);
    expect(screen.queryByRole("menu")).toBeNull();
    expect(outer).not.toHaveBeenCalled();
  });
});
