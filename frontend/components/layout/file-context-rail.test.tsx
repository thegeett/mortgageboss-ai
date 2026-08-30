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
vi.mock("@/lib/api/documents", () => ({ useLoanFileDocuments: () => q([]) }));
vi.mock("@/lib/api/verification", () => ({ useVerification: () => q(undefined) }));

import { FileContextRail } from "./file-context-rail";

afterEach(() => {
  cleanup();
  data.file = undefined;
  data.dti = undefined;
  data.ltv = undefined;
  data.reserves = undefined;
  data.activity = undefined;
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

  it("shows the Documents section only on the documents tab", () => {
    renderRail();
    expect(screen.queryByText("Documents")).toBeNull();
    cleanup();
    pathname.current = "/loan-files/abc/documents";
    renderRail();
    expect(screen.queryByText("Documents")).not.toBeNull();
  });

  it("does not show it on a route that merely ends with the same word", () => {
    pathname.current = "/loan-files/abc/conditions/documents";
    renderRail();
    expect(screen.queryByText("Documents")).toBeNull();
  });
});
