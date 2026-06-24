// @vitest-environment jsdom
import type { DocumentResponse } from "@/lib/types/document";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DocumentList } from "./document-list";

afterEach(cleanup);

function doc(overrides: Partial<DocumentResponse> = {}): DocumentResponse {
  return {
    id: "d1",
    loan_file_id: "f1",
    original_filename: "paystub.pdf",
    mime_type: "application/pdf",
    file_size_bytes: 1024,
    document_type: "pay_stub",
    category: "income_employment",
    tier: "tier_1",
    summary: null,
    classification_confidence: 0.9,
    status: "completed",
    upload_source: "user_upload",
    uploaded_by_user_id: "u1",
    created_at: "2026-06-12T10:00:00Z",
    updated_at: "2026-06-12T10:00:00Z",
    version: 1,
    is_current: true,
    version_group_id: null,
    supersedes_document_id: null,
    version_count: 1,
    possible_duplicate: false,
    staleness: { is_stale: false, kind: null, reason: null, resolution: null, as_of_date: null },
    package_fit: { fit: true, reason: null },
    standard_name: "",
    package_qualification: { qualified: false, reason: "not_extracted" },
    ...overrides,
  };
}

describe("DocumentList — loading → content | empty | error", () => {
  it("shows a loading cue (and no rows) while pending", () => {
    const { container } = render(
      <DocumentList documents={undefined} isPending isError={false} onSelect={vi.fn()} />,
    );
    expect(screen.getByText("Loading documents")).toBeDefined(); // sr-only status
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
    // No document rows while loading (skeletons only).
    expect(screen.queryByText("paystub.pdf")).toBeNull();
  });

  it("shows the documents once loaded", () => {
    render(
      <DocumentList documents={[doc()]} isPending={false} isError={false} onSelect={vi.fn()} />,
    );
    expect(screen.getByText("paystub.pdf")).toBeDefined();
    expect(screen.queryByText("Loading documents")).toBeNull();
  });

  it("shows the empty state when loaded with no documents", () => {
    render(<DocumentList documents={[]} isPending={false} isError={false} onSelect={vi.fn()} />);
    expect(screen.getByText("No documents yet")).toBeDefined();
  });

  it("renders a Tier 2 document's summary gist (LP-65)", () => {
    const gist = "Tri-merge consumer credit report dated 2026-06-01.";
    render(
      <DocumentList
        documents={[doc({ tier: "tier_2", document_type: "credit_report", summary: gist })]}
        isPending={false}
        isError={false}
        onSelect={vi.fn()}
      />,
    );
    expect(screen.getByText(gist)).toBeDefined();
  });

  it("renders no summary line for a Tier 1 document (summary null)", () => {
    render(
      <DocumentList
        documents={[doc({ summary: null })]}
        isPending={false}
        isError={false}
        onSelect={vi.fn()}
      />,
    );
    expect(screen.getByText("paystub.pdf")).toBeDefined(); // row renders; no summary line
  });

  it("shows an error state with retry when the load fails", () => {
    const onRetry = vi.fn();
    render(
      <DocumentList
        documents={undefined}
        isPending={false}
        isError
        onRetry={onRetry}
        onSelect={vi.fn()}
      />,
    );
    expect(screen.getByText("Couldn’t load your documents")).toBeDefined();
  });
});

describe("DocumentList — versioning + staleness (LP-71)", () => {
  it("shows the version label for a multi-version document", () => {
    render(
      <DocumentList
        documents={[doc({ version: 2, version_count: 2 })]}
        isPending={false}
        isError={false}
        onSelect={vi.fn()}
      />,
    );
    expect(screen.getByText("v2 of 2")).toBeDefined();
  });

  it("shows a calm staleness badge on a stale document", () => {
    render(
      <DocumentList
        documents={[
          doc({
            staleness: {
              is_stale: true,
              kind: "aged",
              reason: "Dated 45 days ago",
              resolution: null,
              as_of_date: null,
            },
          }),
        ]}
        isPending={false}
        isError={false}
        onSelect={vi.fn()}
      />,
    );
    expect(screen.getByText("May be stale")).toBeDefined();
  });

  it("hides historical (superseded) versions from the main list", () => {
    render(
      <DocumentList
        documents={[
          doc({ id: "cur", original_filename: "current.pdf", is_current: true }),
          doc({ id: "old", original_filename: "old.pdf", is_current: false }),
        ]}
        isPending={false}
        isError={false}
        onSelect={vi.fn()}
      />,
    );
    expect(screen.getByText("current.pdf")).toBeDefined();
    expect(screen.queryByText("old.pdf")).toBeNull(); // reached via version history, not the list
  });

  it("gently surfaces other current documents of the same type", () => {
    render(
      <DocumentList
        documents={[
          doc({ id: "a", document_type: "pay_stub", category: "income_employment" }),
          doc({ id: "b", document_type: "pay_stub", category: "income_employment" }),
        ]}
        isPending={false}
        isError={false}
        onSelect={vi.fn()}
      />,
    );
    // Each row notes the other same-type document (informational, not blocking).
    expect(screen.getAllByText(/1 other/i).length).toBe(2);
  });
});

describe("DocumentList — standard naming + package-ready (LP-72)", () => {
  it("shows the derived standard name as the primary label", () => {
    render(
      <DocumentList
        documents={[doc({ standard_name: "Pay-Stub_Thermofisher-PPD_2026-05-22" })]}
        isPending={false}
        isError={false}
        onSelect={vi.fn()}
      />,
    );
    expect(screen.getByText("Pay-Stub_Thermofisher-PPD_2026-05-22")).toBeDefined();
    expect(screen.queryByText("paystub.pdf")).toBeNull(); // raw filename not the primary label
  });

  it("shows a package-ready indicator on a qualified document", () => {
    render(
      <DocumentList
        documents={[doc({ package_qualification: { qualified: true, reason: null } })]}
        isPending={false}
        isError={false}
        onSelect={vi.fn()}
      />,
    );
    expect(screen.getByLabelText("Package-ready")).toBeDefined();
  });

  it("shows no package-ready indicator when not qualified", () => {
    render(
      <DocumentList
        documents={[doc({ package_qualification: { qualified: false, reason: "stale" } })]}
        isPending={false}
        isError={false}
        onSelect={vi.fn()}
      />,
    );
    expect(screen.queryByLabelText("Package-ready")).toBeNull();
  });
});
