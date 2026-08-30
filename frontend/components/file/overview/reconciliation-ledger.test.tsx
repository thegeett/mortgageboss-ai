// @vitest-environment jsdom
import type { ReconciliationRow, RowFinding } from "@/lib/types/reconciliation";
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const useReconciliation = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/reconciliation", () => ({ useReconciliation }));

import { ReconciliationLedger } from "./reconciliation-ledger";

afterEach(() => {
  cleanup();
  useReconciliation.mockReset();
});

function row(overrides: Partial<ReconciliationRow> = {}): ReconciliationRow {
  return {
    field_key: "base_monthly_income",
    label: "Base monthly income",
    stated_value: "8812.50",
    found_value: "3945.93",
    unit: "money",
    agreement: "differs",
    source: {
      document_id: "doc-9",
      filename: "kapadiya-w2-2024.pdf",
      page: 2,
      snippet: "Wages, tips, other comp 47,351.16",
    },
    source_note: null,
    finding: null,
    ...overrides,
  };
}

function loaded(rows: ReconciliationRow[]) {
  useReconciliation.mockReturnValue({
    data: rows,
    isPending: false,
    isError: false,
    refetch: vi.fn(),
  });
}

describe("ReconciliationLedger", () => {
  it("formats a money row as currency", () => {
    // The server sends `8812.50` raw so the app's one money formatter can read
    // it. If the unit is ignored the ledger becomes the only screen in the
    // product printing bare amounts — and nothing throws when it does.
    loaded([row()]);
    render(<ReconciliationLedger fileId="LF-96SV" />);
    expect(screen.getByText("$8,812.50")).toBeTruthy();
    expect(screen.getByText("$3,945.93")).toBeTruthy();
  });

  it("leaves a text row alone", () => {
    loaded([
      row({
        field_key: "employer",
        label: "Employer",
        unit: "text",
        stated_value: "Ambio, Inc.",
        found_value: "Ambio, DBA Ambio, Inc",
      }),
    ]);
    render(<ReconciliationLedger fileId="LF-96SV" />);
    expect(screen.getByText("Ambio, Inc.")).toBeTruthy();
  });

  it("states each row's agreement as a word, not only a colour", () => {
    // SPEC rule: colour AND glyph AND word. A rail alone fails for the ~1 in 12
    // men with a colour vision deficiency, and on a printed file.
    loaded([row({ agreement: "differs" })]);
    render(<ReconciliationLedger fileId="LF-96SV" />);
    expect(screen.getByText("Differs")).toBeTruthy();
  });

  it("links the source to that document", () => {
    loaded([row()]);
    render(<ReconciliationLedger fileId="LF-96SV" />);
    const link = screen.getByRole("link", { name: /kapadiya-w2-2024\.pdf/ });
    expect(link.getAttribute("href")).toBe("/loan-files/LF-96SV/documents?doc=doc-9");
  });

  it("shows the page and the snippet as the evidence", () => {
    // The page is shown but is not a link target until LP-UI-030 builds a page
    // canvas. The snippet is what a processor would open the page to read.
    loaded([row()]);
    render(<ReconciliationLedger fileId="LF-96SV" />);
    expect(screen.getByRole("link", { name: /p\.2/ })).toBeTruthy();
    expect(screen.getByText(/Wages, tips, other comp 47,351\.16/)).toBeTruthy();
  });

  it("gives the reason when a row has no source", () => {
    // Paired with a sourced row on purpose: a file where NOTHING has a source is
    // the empty state below, not a ledger of five reasons.
    loaded([
      row(),
      row({
        field_key: "appraised_value",
        label: "Appraised value",
        found_value: null,
        agreement: "missing",
        source: null,
        source_note: "No appraisal has been extracted for this file.",
      }),
    ]);
    render(<ReconciliationLedger fileId="LF-96SV" />);
    expect(screen.getByText("No appraisal has been extracted for this file.")).toBeTruthy();
    expect(screen.getAllByRole("link")).toHaveLength(1);
  });

  it("counts only the rows that agree", () => {
    loaded([row({ agreement: "match" }), row({ field_key: "employer", agreement: "differs" })]);
    render(<ReconciliationLedger fileId="LF-96SV" />);
    expect(screen.getByText("1 of 2 agree")).toBeTruthy();
  });

  it("says nothing has been read rather than flagging five absent documents", () => {
    // A DRAFT file with no extractions: every row is a sourceless "not found",
    // which is true and useless — it reports one missing-documents problem as
    // five separate discrepancies with the application.
    loaded([
      row({ found_value: null, agreement: "missing", source: null, source_note: "No W-2." }),
      row({
        field_key: "appraised_value",
        found_value: null,
        agreement: "missing",
        source: null,
        source_note: "No appraisal.",
      }),
    ]);
    render(<ReconciliationLedger fileId="LF-96SV" />);
    expect(screen.getByText(/No document has been read for this file yet/)).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("keeps the ledger when even one row has a source", () => {
    loaded([
      row(),
      row({
        field_key: "appraised_value",
        found_value: null,
        agreement: "missing",
        source: null,
        source_note: "No appraisal.",
      }),
    ]);
    render(<ReconciliationLedger fileId="LF-96SV" />);
    expect(screen.getByRole("table")).toBeTruthy();
    expect(screen.queryByText(/No document has been read/)).toBeNull();
  });

  it("renders an empty file without a table", () => {
    loaded([]);
    render(<ReconciliationLedger fileId="LF-96SV" />);
    expect(screen.getByText(/nothing to reconcile on this file yet/)).toBeTruthy();
  });

  it("offers a retry when the read fails", () => {
    const refetch = vi.fn();
    useReconciliation.mockReturnValue({
      data: undefined,
      isPending: false,
      isError: true,
      refetch,
    });
    render(<ReconciliationLedger fileId="LF-96SV" />);
    expect(screen.getByText(/Couldn't load the reconciliation/)).toBeTruthy();
  });

  it("shows a busy state while loading, and no stale count", () => {
    useReconciliation.mockReturnValue({
      data: undefined,
      isPending: true,
      isError: false,
      refetch: vi.fn(),
    });
    render(<ReconciliationLedger fileId="LF-96SV" />);
    expect(screen.getByText("Loading the reconciliation")).toBeTruthy();
    expect(screen.queryByText(/agree$/)).toBeNull();
  });

  it("puts the agreement on the row it belongs to", () => {
    // Two rows, two different agreements: a component that resolved the tone
    // once and reused it would pass every test above and fail this one.
    loaded([
      row({ field_key: "a", label: "Base monthly income", agreement: "match" }),
      row({ field_key: "b", label: "Checking balance", agreement: "differs" }),
    ]);
    render(<ReconciliationLedger fileId="LF-96SV" />);
    const rows = screen.getAllByRole("row");
    const income = rows.find((r) => within(r).queryByText("Base monthly income"));
    const checking = rows.find((r) => within(r).queryByText("Checking balance"));
    expect(within(income as HTMLElement).getByText("Agrees")).toBeTruthy();
    expect(within(checking as HTMLElement).getByText("Differs")).toBeTruthy();
  });

  describe("when the rule engine has ruled on the same question (A20)", () => {
    const finding: RowFinding = {
      finding_id: "f-1",
      rule_id: "xsrc.income.employer_name_consistency",
      status: "red",
      message: "Documented employer not among the stated employers: AMBIOPHARM, INC.",
      count: 1,
    };

    it("shows the engine's verdict, not the ledger's own", () => {
      // THE property. The ledger says these two agree; the engine says blocking.
      // They can genuinely disagree — the income variance is overrideable per
      // lender (LP-80) and the read model does not resolve overlays. The finding
      // wins, or the ledger is quietly contradicting the screen it links to.
      loaded([row({ agreement: "match", finding })]);
      render(<ReconciliationLedger fileId="LF-96SV" />);
      expect(screen.getByText("Blocking")).toBeTruthy();
      expect(screen.queryByText("Agrees")).toBeNull();
    });

    it("keeps the comparison as the evidence beneath it", () => {
      loaded([row({ agreement: "match", finding })]);
      render(<ReconciliationLedger fileId="LF-96SV" />);
      expect(screen.getByText("$8,812.50")).toBeTruthy();
      expect(screen.getByText("$3,945.93")).toBeTruthy();
    });

    it("quotes the rule's own words and links to the screen that owns it", () => {
      loaded([row({ finding })]);
      render(<ReconciliationLedger fileId="LF-96SV" />);
      const link = screen.getByRole("link", { name: /Documented employer not among/ });
      expect(link.getAttribute("href")).toBe("/loan-files/LF-96SV/verification");
    });

    it("says how many findings it is standing in for", () => {
      loaded([row({ finding: { ...finding, count: 3 } })]);
      render(<ReconciliationLedger fileId="LF-96SV" />);
      expect(screen.getByText(/\(\+2 more\)/)).toBeTruthy();
    });

    it("still says what the ledger observed in an empty cell", () => {
      // The verdict belongs on the rail. A cell with no value has to report THAT
      // — "Warning" in the Found column answers a different question and loses
      // the one the column exists to answer.
      loaded([row({ found_value: null, agreement: "missing", finding })]);
      render(<ReconciliationLedger fileId="LF-96SV" />);
      expect(screen.getByText("Not found")).toBeTruthy();
      expect(screen.getByText("Blocking")).toBeTruthy();
    });

    it("leaves a row with no finding reporting its own comparison", () => {
      loaded([row({ agreement: "match", finding: null })]);
      render(<ReconciliationLedger fileId="LF-96SV" />);
      expect(screen.getByText("Agrees")).toBeTruthy();
    });
  });
});

describe("the verdict owns every channel, not just the rail", () => {
  // A20: where the engine has ruled, that verdict wins. The empty cell needed
  // this split and got it; the VALUE cell next to it was still painted from the
  // ledger's own `agreement`, so a row the engine calls satisfied rendered a
  // green rail, a green glyph and an amber number — the overruled answer back in
  // a channel the reader takes for the verdict.
  const passing: RowFinding = {
    finding_id: "f1",
    rule_id: "xsrc.income.stated_vs_documented",
    status: "green" as const,
    message: "Within the lender's variance.",
    count: 1,
  };

  it("does not paint the value amber when the engine passed the row", () => {
    loaded([
      row({
        field_key: "base_monthly_income",
        agreement: "differs",
        stated_value: "10000.00",
        found_value: "11500.00",
        unit: "money",
        finding: passing,
      }),
    ]);
    render(<ReconciliationLedger fileId="LF-96SV" />);
    const cell = screen.getByText(/11,500/).closest("td");
    expect(cell?.className).not.toContain("text-warning");
  });

  it("still paints it amber when the engine flags the row", () => {
    loaded([
      row({
        field_key: "base_monthly_income",
        agreement: "differs",
        stated_value: "10000.00",
        found_value: "11500.00",
        unit: "money",
        finding: { ...passing, status: "yellow" as const, message: "Income variance." },
      }),
    ]);
    render(<ReconciliationLedger fileId="LF-96SV" />);
    expect(screen.getByText(/11,500/).closest("td")?.className).toContain("text-warning");
  });

  it("falls back to its own comparison where no rule has ruled", () => {
    loaded([
      row({
        field_key: "appraised_value",
        agreement: "differs",
        stated_value: "720000.00",
        found_value: "700000.00",
        unit: "money",
        finding: null,
      }),
    ]);
    render(<ReconciliationLedger fileId="LF-96SV" />);
    expect(screen.getByText(/700,000/).closest("td")?.className).toContain("text-warning");
  });
});
