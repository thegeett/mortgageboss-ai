// @vitest-environment jsdom
import type { DocumentResponse } from "@/lib/types/document";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DOCUMENT_COLUMNS, DocumentList, DocumentRow } from "./document-list";

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
    period: null,
    package_qualification: { qualified: false, reason: "not_extracted" },
    ...overrides,
  };
}

describe("DocumentList — loading → content | empty | error", () => {
  it("shows a loading cue (and no rows) while pending", () => {
    const { container } = render(
      <DocumentList
        documents={undefined}
        isPending
        isError={false}
        onOpen={vi.fn()}
        onOpenDetails={vi.fn()}
      />,
    );
    expect(screen.getByText("Loading documents")).toBeDefined(); // sr-only status
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
    // No document rows while loading (skeletons only).
    expect(screen.queryByText("paystub.pdf")).toBeNull();
  });

  it("shows the documents once loaded", () => {
    render(
      <DocumentList
        documents={[doc()]}
        isPending={false}
        isError={false}
        onOpen={vi.fn()}
        onOpenDetails={vi.fn()}
      />,
    );
    expect(screen.getByText("paystub.pdf")).toBeDefined();
    expect(screen.queryByText("Loading documents")).toBeNull();
  });

  it("shows the empty state when loaded with no documents", () => {
    render(
      <DocumentList
        documents={[]}
        isPending={false}
        isError={false}
        onOpen={vi.fn()}
        onOpenDetails={vi.fn()}
      />,
    );
    expect(screen.getByText("No documents yet")).toBeDefined();
  });

  it("renders a Tier 2 document's summary gist (LP-65)", () => {
    const gist = "Tri-merge consumer credit report dated 2026-06-01.";
    render(
      <DocumentList
        documents={[doc({ tier: "tier_2", document_type: "credit_report", summary: gist })]}
        isPending={false}
        isError={false}
        onOpen={vi.fn()}
        onOpenDetails={vi.fn()}
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
        onOpen={vi.fn()}
        onOpenDetails={vi.fn()}
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
        onOpen={vi.fn()}
        onOpenDetails={vi.fn()}
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
        onOpen={vi.fn()}
        onOpenDetails={vi.fn()}
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
        onOpen={vi.fn()}
        onOpenDetails={vi.fn()}
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
        onOpen={vi.fn()}
        onOpenDetails={vi.fn()}
      />,
    );
    expect(screen.getByText("current.pdf")).toBeDefined();
    expect(screen.queryByText("old.pdf")).toBeNull(); // reached via version history, not the list
  });

  it("no longer repeats the duplicate cue on every row (LP-UI-019)", () => {
    // This cue used to read "1 other pay stub" under each of two rows — the same
    // fact told twice, once per document, and noticed one row at a time. It moved
    // to the context rail's Duplicates block, where it is one answer for the
    // whole file; file-context-rail.test.tsx pins it there. The signal is not
    // gone, so this asserts WHERE it is not, rather than deleting the property.
    render(
      <DocumentList
        documents={[
          doc({ id: "a", document_type: "pay_stub", category: "income_employment" }),
          doc({ id: "b", document_type: "pay_stub", category: "income_employment" }),
        ]}
        isPending={false}
        isError={false}
        onOpen={vi.fn()}
        onOpenDetails={vi.fn()}
      />,
    );
    // Asserted alongside a POSITIVE. A bare `toBeNull` passes just as well when
    // the list rendered nothing at all — the same shape as a mutation run that
    // finds no tests, which is indistinguishable from one that finds no failures.
    expect(screen.getAllByRole("row").length).toBeGreaterThan(1);
    expect(screen.queryByText(/1 other/i)).toBeNull();
  });

  it("keeps in-flight documents out of the table (LP-UI-019)", () => {
    // They are in the ProcessingStrip above. A classifying document holding a
    // row it changes every few seconds is what moves the settled list.
    render(
      <DocumentList
        documents={[
          doc({ id: "a", standard_name: "Settled W-2", status: "completed" }),
          doc({ id: "b", standard_name: "Arriving now", status: "extracting" }),
        ]}
        isPending={false}
        isError={false}
        onOpen={vi.fn()}
        onOpenDetails={vi.fn()}
      />,
    );
    expect(screen.getByText("Settled W-2")).toBeTruthy();
    expect(screen.queryByText("Arriving now")).toBeNull();
  });

  it("opens a document from the keyboard, not only the mouse", () => {
    // LP-UI-007 shipped a row whose Enter key did something other than what its
    // click did, and made an action reachable only with a pointer.
    const onOpen = vi.fn();
    render(
      <DocumentList
        documents={[doc({ id: "a", standard_name: "Kapadiya pay stub — Feb" })]}
        isPending={false}
        isError={false}
        onOpen={onOpen}
        onOpenDetails={vi.fn()}
      />,
    );
    const row = screen.getByText("Kapadiya pay stub — Feb").closest("tr") as HTMLElement;
    fireEvent.keyDown(row, { key: "Enter" });
    expect(onOpen).toHaveBeenCalledTimes(1);
  });
});

describe("DocumentList — standard naming + package-ready (LP-72)", () => {
  it("shows the derived standard name as the primary label", () => {
    render(
      <DocumentList
        documents={[doc({ standard_name: "Pay-Stub_Thermofisher-PPD_2026-05-22" })]}
        isPending={false}
        isError={false}
        onOpen={vi.fn()}
        onOpenDetails={vi.fn()}
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
        onOpen={vi.fn()}
        onOpenDetails={vi.fn()}
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
        onOpen={vi.fn()}
        onOpenDetails={vi.fn()}
      />,
    );
    expect(screen.queryByLabelText("Package-ready")).toBeNull();
  });

  // LP-105 — the consolidated period line makes same-type documents distinguishable at a glance.
  it("shows the consolidated period line on the card", () => {
    render(
      <DocumentList
        documents={[doc({ period: { label: "Period", value: "Jun 1 - Jun 15, 2026" } })]}
        isPending={false}
        isError={false}
        onOpen={vi.fn()}
        onOpenDetails={vi.fn()}
      />,
    );
    expect(screen.getByText("Period: Jun 1 - Jun 15, 2026")).toBeDefined();
  });

  it("shows no period line when the period is absent (graceful)", () => {
    const { container } = render(
      <DocumentList
        documents={[doc({ period: null })]}
        isPending={false}
        isError={false}
        onOpen={vi.fn()}
        onOpenDetails={vi.fn()}
      />,
    );
    expect(container.textContent).not.toContain("Period:");
  });

  it("distinguishes two same-type documents by their period", () => {
    render(
      <DocumentList
        documents={[
          doc({ id: "a", period: { label: "Period", value: "Jun 1 - Jun 15, 2026" } }),
          doc({ id: "b", period: { label: "Period", value: "Jun 16 - Jun 30, 2026" } }),
        ]}
        isPending={false}
        isError={false}
        onOpen={vi.fn()}
        onOpenDetails={vi.fn()}
      />,
    );
    expect(screen.getByText("Period: Jun 1 - Jun 15, 2026")).toBeDefined();
    expect(screen.getByText("Period: Jun 16 - Jun 30, 2026")).toBeDefined();
  });

  // LP-107 — an unclassified document shows its original filename as the name, while the type
  // indicator still honestly reads "Unknown" (the signal isn't hidden).
  it("shows an unknown document's original filename as the name, and 'Unknown' as the type", () => {
    render(
      <DocumentList
        documents={[
          doc({
            document_type: "unknown",
            standard_name: "Akash W2 Wells 2024.pdf", // backend falls the name back to the filename
            original_filename: "Akash W2 Wells 2024.pdf",
          }),
        ]}
        isPending={false}
        isError={false}
        onOpen={vi.fn()}
        onOpenDetails={vi.fn()}
      />,
    );
    expect(screen.getByText("Akash W2 Wells 2024.pdf")).toBeDefined(); // the real, identifiable name
    expect(screen.getByText(/Unknown/)).toBeDefined(); // the type signal is kept
  });

  it("distinguishes two unknown documents by their real filenames", () => {
    render(
      <DocumentList
        documents={[
          doc({ id: "a", document_type: "unknown", standard_name: "EMD wire receipt.pdf" }),
          doc({ id: "b", document_type: "unknown", standard_name: "Home Value estimate.pdf" }),
        ]}
        isPending={false}
        isError={false}
        onOpen={vi.fn()}
        onOpenDetails={vi.fn()}
      />,
    );
    expect(screen.getByText("EMD wire receipt.pdf")).toBeDefined();
    expect(screen.getByText("Home Value estimate.pdf")).toBeDefined();
  });
});

describe("the real row against the declared columns", () => {
  /**
   * The half `DOCUMENT_COLUMNS` does not cover.
   *
   * The header and the skeleton both map that list; the real row hand-writes its
   * five cells. So the shared list keeps the header and the skeleton in step and
   * says nothing about the rows — while `list-skeleton.test.tsx` describes what it
   * prevents as "a new column reaching the rows and not the skeleton". Add a sixth
   * column today and the header and skeleton grow, the row does not, and the table
   * jumps sideways exactly as that comment describes.
   */
  it("renders one cell per declared column, as the skeleton does", () => {
    const { container } = render(
      <table>
        <tbody>
          <DocumentRow document={doc()} onOpen={() => {}} onOpenDetails={() => {}} />
        </tbody>
      </table>,
    );
    // +1 for the details control, which is a column with no header label — the
    // same shape as the pipeline's actions column. It is deliberately not in
    // DOCUMENT_COLUMNS: that list drives visible headers and skeleton widths,
    // and a nameless control has neither.
    expect(container.querySelector("tr")?.querySelectorAll("td")).toHaveLength(
      DOCUMENT_COLUMNS.length + 1,
    );
  });

  it("opens the DOCUMENT from the row and the DRAWER from the details button", () => {
    // The two answer different questions. A row that did both had to pick one,
    // and it had picked the drawer — so clicking a pay stub showed metadata
    // about the pay stub rather than the pay stub.
    const onOpen = vi.fn();
    const onOpenDetails = vi.fn();
    render(
      <table>
        <tbody>
          <DocumentRow
            document={doc({ standard_name: "Kapadiya pay stub" })}
            onOpen={onOpen}
            onOpenDetails={onOpenDetails}
          />
        </tbody>
      </table>,
    );

    fireEvent.click(screen.getByText("Kapadiya pay stub"));
    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(onOpenDetails).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: /details for/i }));
    expect(onOpenDetails).toHaveBeenCalledTimes(1);
    // The row is a button too: without stopPropagation the drawer opens AND the
    // reviewer navigates underneath it.
    expect(onOpen).toHaveBeenCalledTimes(1);
  });
});
