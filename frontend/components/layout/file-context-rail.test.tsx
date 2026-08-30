// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const pathname = vi.hoisted(() => ({ current: "/loan-files/abc" }));
vi.mock("next/navigation", () => ({ usePathname: () => pathname.current }));

const data = vi.hoisted(() => ({
  file: undefined as unknown,
  dti: undefined as unknown,
  ltv: undefined as unknown,
  reserves: undefined as unknown,
  activity: undefined as unknown,
  documents: [] as unknown[],
  pending: false,
}));
const q = (value: unknown) => ({ data: value, isPending: data.pending });

vi.mock("@/lib/api/loan-files", () => ({
  useLoanFile: () => q(data.file),
  useLoanFileActivity: () => q(data.activity),
}));
vi.mock("@/lib/api/dti", () => ({ useDti: () => q(data.dti) }));
vi.mock("@/lib/api/ltv", () => ({ useLtv: () => q(data.ltv) }));
vi.mock("@/lib/api/calculators", () => ({ useCalculator: () => q(data.reserves) }));
vi.mock("@/lib/api/documents", () => ({ useLoanFileDocuments: () => q(data.documents) }));
vi.mock("@/lib/api/verification", () => ({ useVerification: () => q(undefined) }));

import { FileContextRail } from "./file-context-rail";

afterEach(() => {
  cleanup();
  data.file = undefined;
  data.dti = undefined;
  data.ltv = undefined;
  data.reserves = undefined;
  data.activity = undefined;
  data.documents = [];
  data.pending = false;
  pathname.current = "/loan-files/abc";
});

function renderRail() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <FileContextRail fileId="abc" />
    </QueryClientProvider>,
  );
}

/** The value rendered beside a metric label. */
function metric(label: string): string {
  const row = screen.getByText(label).parentElement;
  if (!row) throw new Error(`no row for "${label}"`);
  return (row.textContent ?? "").replace(label, "").trim();
}

describe("FileContextRail", () => {
  it("shows skeletons, not em dashes, while the file is loading", () => {
    // An em dash MEANS "this file has no such value". Using it for "not fetched
    // yet" tells a processor the file is missing a figure it actually has — and
    // the tabs beside the rail show skeletons, so the rail contradicted them.
    data.pending = true;
    renderRail();
    expect(metric("Amount")).toBe("");
    expect(metric("Back-end DTI")).toBe("");
  });

  it("shows an em dash once loaded and the value really is absent", () => {
    data.file = { status: "in_processing", loan_amount: null };
    renderRail();
    expect(metric("Amount")).toBe("—");
  });

  it("says Gated for a gated DTI rather than an em dash", () => {
    // LP-375: the engine nulls the ratio rather than fabricating a 0, so "—"
    // would read as "this file has no DTI" instead of "an input is unknown".
    data.dti = { gated: true, back_end_dti: null, front_end_dti: null, limit: {} };
    renderRail();
    expect(metric("Back-end DTI")).toBe("Gated");
  });

  it("renders a 0% ratio, which is a real value and not an absent one", () => {
    data.dti = { gated: false, back_end_dti: "0", front_end_dti: "0", limit: {} };
    renderRail();
    expect(metric("Back-end DTI")).toBe("0%");
  });

  it("shows the documents sections only on the documents tab", () => {
    // LP-UI-019 split the one "Documents" block into Coverage, Freshness and
    // Duplicates. The property is unchanged — these appear on that tab and
    // nowhere else — so the assertion follows the rename rather than the block.
    renderRail();
    expect(screen.queryByText("Coverage")).toBeNull();
    cleanup();
    pathname.current = "/loan-files/abc/documents";
    renderRail();
    expect(screen.queryByText("Coverage")).not.toBeNull();
    expect(screen.queryByText("Freshness")).not.toBeNull();
    expect(screen.queryByText("Duplicates")).not.toBeNull();
  });

  it("does not show them on a route that merely ends with the same word", () => {
    pathname.current = "/loan-files/abc/conditions/documents";
    renderRail();
    expect(screen.queryByText("Coverage")).toBeNull();
  });
});

describe("FileContextRail — documents coverage, freshness, duplicates (LP-UI-019)", () => {
  function doc(overrides: Record<string, unknown> = {}) {
    return {
      id: "d1",
      original_filename: "w2.pdf",
      standard_name: "W-2 — Ambio — 2024",
      status: "completed",
      is_current: true,
      document_type: "w2",
      file_size_bytes: 1024,
      created_at: "2026-08-01T00:00:00Z",
      period: null,
      summary: null,
      version: 1,
      version_count: 1,
      staleness: { is_stale: false, kind: null, reason: null, resolution: null, as_of_date: null },
      package_qualification: { qualified: true, reason: null },
      ...overrides,
    };
  }

  function renderDocsTab(documents: unknown[]) {
    pathname.current = "/loan-files/abc/documents";
    data.documents = documents;
    renderRail();
  }

  it("counts qualified documents against the current ones only", () => {
    // A superseded version is reached through the drawer's version history, so
    // counting it would make "1 of 2" describe a list the processor cannot see.
    renderDocsTab([doc(), doc({ id: "d2", is_current: false })]);
    expect(screen.getByText("1 / 1")).toBeTruthy();
  });

  it("reports the backend's own reason for each document that is not qualified", () => {
    // The four criteria are checked server-side in priority order and the FIRST
    // failure is reported. The rail labels that reason; it does not re-derive it.
    renderDocsTab([
      doc(),
      doc({ id: "d2", package_qualification: { qualified: false, reason: "untyped" } }),
    ]);
    expect(screen.getByText("Not recognised")).toBeTruthy();
  });

  it("says nothing is stale rather than showing an empty heading", () => {
    renderDocsTab([doc()]);
    expect(screen.getByText(/Nothing on this file has passed its window/)).toBeTruthy();
  });

  it("names the documents that have passed their window", () => {
    renderDocsTab([
      doc({
        staleness: {
          is_stale: true,
          kind: "age",
          reason: "60 days old at close",
          resolution: null,
          as_of_date: null,
        },
      }),
    ]);
    expect(screen.getByText("60 days old at close")).toBeTruthy();
  });

  it("does not chase a staleness the processor has already answered", () => {
    // LP-71 records the resolution (replaced / waived / accepted) for this reason.
    renderDocsTab([
      doc({
        staleness: {
          is_stale: true,
          kind: "age",
          reason: "60 days old at close",
          resolution: "accepted",
          as_of_date: null,
        },
      }),
    ]);
    expect(screen.queryByText("60 days old at close")).toBeNull();
  });

  it("answers the duplicate question once for the file, not once per row", () => {
    // The property moved here from DocumentList, where two pay stubs each read
    // "1 other pay stub" — the same fact told twice.
    renderDocsTab([
      doc({ id: "a", document_type: "pay_stub" }),
      doc({ id: "b", document_type: "pay_stub" }),
    ]);
    expect(screen.getByText(/2 × Pay stub/i)).toBeTruthy();
  });

  it("says so plainly when no two documents share a type", () => {
    renderDocsTab([doc({ document_type: "w2" }), doc({ id: "b", document_type: "pay_stub" })]);
    expect(screen.getByText(/No two current documents share a type/)).toBeTruthy();
  });
});
