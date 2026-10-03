// @vitest-environment jsdom
/** LP-953 — her link actions on an item: Link a document (with a page), Change, Upload here. */
import type { Condition, ConditionItem } from "@/lib/types/conditions";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const calls = vi.hoisted(() => ({
  link: [] as unknown[],
  upload: [] as unknown[],
  update: [] as unknown[],
}));
vi.mock("@/lib/api/conditions", () => ({
  useLinkItemDocument: () => ({ isPending: false, mutate: (b: unknown) => calls.link.push(b) }),
  useUploadToItem: () => ({ isPending: false, mutate: (b: unknown) => calls.upload.push(b) }),
  useUpdateItem: () => ({ isPending: false, mutate: (b: unknown) => calls.update.push(b) }),
}));
vi.mock("@/lib/api/documents", () => ({
  useLoanFileDocuments: () => ({
    data: [
      { id: "d1", standard_name: "Service invoice — credit report", original_filename: "a.pdf" },
      { id: "d2", standard_name: "Credit report", original_filename: "b.pdf" },
    ],
  }),
}));

import { ItemLinkActions } from "./item-links";

afterEach(() => {
  cleanup();
  calls.link = [];
  calls.upload = [];
  calls.update = [];
});

const CONDITION = { id: "c1" } as Condition;
const ITEM = {
  id: "i1",
  name: "Credit report invoice",
  option: "i_will_do_it",
} as ConditionItem;

describe("ItemLinkActions", () => {
  it("links the chosen document with its page", () => {
    render(<ItemLinkActions fileId="f1" condition={CONDITION} item={ITEM} />);
    fireEvent.click(screen.getByRole("button", { name: "Link a document" }));
    fireEvent.change(screen.getByLabelText("Document on this file"), { target: { value: "d1" } });
    fireEvent.change(screen.getByLabelText("Page"), { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: "Link" }));
    expect(calls.link).toEqual([
      { conditionId: "c1", itemId: "i1", document_id: "d1", page: 2, replace_document_id: null },
    ]);
  });

  it("changes a link: the old document is not offered and is sent as the one replaced", () => {
    render(
      <ItemLinkActions fileId="f1" condition={CONDITION} item={ITEM} replaceDocumentId="d2" />,
    );
    const options = Array.from(
      (screen.getByLabelText("Change to") as HTMLSelectElement).options,
    ).map((o) => o.value);
    expect(options).toEqual(["", "d1"]);
    fireEvent.change(screen.getByLabelText("Change to"), { target: { value: "d1" } });
    fireEvent.click(screen.getByRole("button", { name: "Use this document" }));
    expect(calls.link).toEqual([
      { conditionId: "c1", itemId: "i1", document_id: "d1", page: null, replace_document_id: "d2" },
    ]);
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
    fireEvent.change(screen.getByLabelText("Ask someone for Credit report invoice"), {
      target: { value: "lo" },
    });
    expect(calls.update).toEqual([
      { conditionId: "c1", itemId: "i1", option: "ask_third_party", performers: ["lo"] },
    ]);
  });

  it("offers every recipient an ask reaches, and routes the insurance agent to their own email", () => {
    // LP-955 REVIEW: four of the seven were offered, so the insurance, HOA and employer emails were
    // unreachable from the only door that delegates her task — and an insurance ask sent as "Someone
    // else" lands in the other-party draft without the mortgagee clause the insurance email carries.
    render(<ItemLinkActions fileId="f1" condition={CONDITION} item={ITEM} />);
    const select = screen.getByLabelText("Ask someone for Credit report invoice");
    const offered = [...select.querySelectorAll("option")]
      .map((o) => (o as HTMLOptionElement).value)
      .filter((v) => v !== "");
    expect(offered).toEqual([
      "lo",
      "borrower",
      "title",
      "insurance",
      "hoa",
      "employer",
      "other_party",
    ]);
    // The absences, each deliberate: her own task, Title's shared email, and the lender's draft.
    expect(offered).not.toContain("processor");
    expect(offered).not.toContain("attorney");
    expect(offered).not.toContain("lender");
    expect(offered).not.toContain("appraiser");
    fireEvent.change(select, { target: { value: "insurance" } });
    expect(calls.update).toEqual([
      { conditionId: "c1", itemId: "i1", option: "ask_third_party", performers: ["insurance"] },
    ]);
  });

  it("asks the borrower as the borrower's ask, and is not offered on an ask", () => {
    const { unmount } = render(<ItemLinkActions fileId="f1" condition={CONDITION} item={ITEM} />);
    fireEvent.change(screen.getByLabelText("Ask someone for Credit report invoice"), {
      target: { value: "borrower" },
    });
    expect(calls.update).toEqual([
      { conditionId: "c1", itemId: "i1", option: "ask_borrower", performers: ["borrower"] },
    ]);
    unmount();
    const asked = { ...ITEM, option: "ask_third_party" } as ConditionItem;
    render(<ItemLinkActions fileId="f1" condition={CONDITION} item={asked} />);
    expect(screen.queryByLabelText("Ask someone for Credit report invoice")).toBeNull();
  });
});
