// @vitest-environment jsdom
/**
 * S3-07 and S3-08 (LP-923): the document card, code's checks with their reasons, the failed-check
 * callout with the re-ask and "Accept anyway…", and the large-deposit finding with its four figures.
 */
import type { Condition, ConditionEvidence } from "@/lib/types/conditions";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const calls = vi.hoisted(() => ({
  reask: [] as unknown[],
  accept: [] as unknown[],
  answer: [] as unknown[],
}));
vi.mock("@/lib/api/conditions", () => ({
  useReaskEvidence: () => ({ isPending: false, mutate: (body: unknown) => calls.reask.push(body) }),
  useAcceptEvidence: () => ({
    isPending: false,
    mutate: (body: unknown) => calls.accept.push(body),
  }),
  useAnswerFinding: () => ({
    isPending: false,
    mutate: (body: unknown) => calls.answer.push(body),
  }),
}));

import { EvidenceSection } from "./evidence-section";

afterEach(cleanup);

const DASH = "–";

const S3_07: ConditionEvidence = {
  id: "e1",
  item_id: "i1",
  document_id: "d1",
  title: "Capital One statement ··9912 · August 2026 · 5 pages",
  arrived_at: "2026-09-02T13:14:00Z",
  via_upload_link: true,
  status: "checked",
  checks: [
    {
      check: "right_account",
      label: "Right account",
      result: "passed",
      reason: "Capital One ending 9912, matches the condition",
    },
    {
      check: "all_pages",
      label: "All pages",
      result: "failed",
      reason: `pages 1${DASH}5 of 6 — page 6 is missing`,
    },
  ],
  findings: [],
  failed: true,
  accepted_reason: null,
  reask: "page 6",
  superseded: null,
  replaced: false,
};

const S3_08: ConditionEvidence = {
  ...S3_07,
  id: "e2",
  title: "Capital One statements ··9912 · July and August 2026 · 12 pages",
  checks: [
    {
      check: "covers_required_funds",
      label: "Enough for closing",
      result: "passed",
      reason: "verified $41,914.42 against $38,210.40 required",
    },
    {
      check: "no_large_deposit",
      label: "No unexplained large deposit",
      result: "failed",
      reason: "08/21/2026 mobile deposit $4,000.00",
    },
  ],
  findings: [
    {
      kind: "large_deposit",
      citation: "Fannie Mae B3-4.2-02",
      date: "2026-08-21",
      amount: "4000.00",
      description: "Mobile Deposit",
      income: "5741.32",
      threshold: "2870.66",
      assets_without: "37914.42",
      required: "38210.40",
      needed: true,
      status: "open",
      reason: null,
    },
  ],
  failed: true,
  reask: null,
};

function condition(evidence: ConditionEvidence[], code = "6132"): Condition {
  return {
    id: "c1",
    lender_code: code,
    prep_status: "waiting",
    waiting_on: "borrower",
    evidence,
  } as Condition;
}

describe("EvidenceSection", () => {
  it("keeps a superseded failure as a record, with nothing to act on (LP-937)", () => {
    const replaced: ConditionEvidence = {
      ...S3_08,
      checks: [...S3_07.checks, ...S3_08.checks],
      failed: false,
      reask: null,
      superseded: "Replaced by Capital One statements ··9912 · July and August 2026 · 12 pages",
      replaced: true,
    };
    render(<EvidenceSection fileId="f1" condition={condition([replaced], "7086")} />);
    expect(
      screen.getByText(
        "Replaced by Capital One statements ··9912 · July and August 2026 · 12 pages",
      ),
    ).toBeDefined();
    // Its checks stay as they were: the history of what arrived is not rewritten.
    expect(screen.getByText(`pages 1${DASH}5 of 6 — page 6 is missing`)).toBeDefined();
    // Nothing to act on: no re-ask, no accept anyway, no finding answers.
    expect(screen.queryByRole("button", { name: /please send/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /Accept anyway/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Ask the borrower to explain it/ })).toBeNull();
    expect(screen.queryByText(/New finding/)).toBeNull();
  });

  it("keeps the deposit on a superseded statement that is still evidence (LP-937 review)", () => {
    // July short on its own, carrying the open deposit; August met the total. July still goes in the
    // package, so its deposit still holds 7086 — it must be on screen and answerable.
    const stillEvidence: ConditionEvidence = {
      ...S3_08,
      failed: false,
      superseded:
        "Still evidence — enough for closing was met once Capital One statement ··9912 · August 2026 · 6 pages arrived",
      replaced: false,
    };
    render(<EvidenceSection fileId="f1" condition={condition([stillEvidence], "7086")} />);
    expect(screen.getByText(/Still evidence — enough for closing was met once/)).toBeDefined();
    expect(screen.getByRole("button", { name: /Ask the borrower to explain it/ })).toBeDefined();
  });

  it("is S3-07: the card, the checks, the callout and its two answers", () => {
    calls.reask = [];
    calls.accept = [];
    render(<EvidenceSection fileId="f1" condition={condition([S3_07])} />);
    expect(screen.getByText("Capital One statement ··9912 · August 2026 · 5 pages")).toBeDefined();
    expect(
      screen.getByText(/Arrived through the borrower upload link · Sep 2, 9:14 AM/),
    ).toBeDefined();
    expect(screen.getByRole("link", { name: "Open" }).getAttribute("href")).toBe(
      "/loan-files/f1/documents?doc=d1",
    );
    expect(screen.getByText(`pages 1${DASH}5 of 6 — page 6 is missing`)).toBeDefined();
    expect(screen.getByText("Not ready: 1 check failed.")).toBeDefined();
    expect(screen.getByText("Waiting on Borrower")).toBeDefined();
    fireEvent.click(screen.getByRole("button", { name: /please send page 6/ }));
    expect(calls.reask).toEqual([{ conditionId: "c1", evidenceId: "e1" }]);
    fireEvent.click(screen.getByRole("button", { name: "Accept anyway…" }));
    const accept = screen.getByRole("button", { name: "Accept" }) as HTMLButtonElement;
    expect(accept.disabled).toBe(true); // a reason first
    fireEvent.change(screen.getByLabelText("Why you are accepting it"), {
      target: { value: "blank back page" },
    });
    fireEvent.click(accept);
    expect(calls.accept).toEqual([
      { conditionId: "c1", evidenceId: "e1", reason: "blank back page" },
    ]);
  });

  it("is S3-08: the finding with its four figures, computed by code", () => {
    calls.answer = [];
    render(<EvidenceSection fileId="f1" condition={condition([S3_08], "7086")} />);
    expect(screen.getByText("New finding: a large deposit needs sourcing")).toBeDefined();
    expect(screen.getByText("Fannie Mae B3-4.2-02")).toBeDefined();
    for (const figure of ["$4,000.00", "$2,870.66", "$37,914.42", "$38,210.40"]) {
      expect(screen.getByText(figure)).toBeDefined();
    }
    expect(
      screen.getByText("Large-deposit threshold: 50% of $5,741.32 monthly income"),
    ).toBeDefined();
    // The deposit is not a failed CHECK callout — it is its own box.
    expect(screen.queryByText(/Not ready:/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Ask the borrower to explain it" }));
    expect(calls.answer).toEqual([
      { conditionId: "c1", evidenceId: "e2", index: 0, answer: "ask" },
    ]);
    expect(screen.getByText(/All figures above are computed by code/)).toBeDefined();
  });
});
