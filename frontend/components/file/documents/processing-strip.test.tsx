// @vitest-environment jsdom
import type { DocumentResponse } from "@/lib/types/document";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ProcessingStrip } from "./processing-strip";

afterEach(cleanup);

function doc(overrides: Partial<DocumentResponse> = {}): DocumentResponse {
  return {
    id: "d1",
    loan_file_id: "f1",
    original_filename: "w2.pdf",
    standard_name: "W-2 — Ambio — 2024",
    status: "completed",
    is_current: true,
    document_type: "w2",
    category: "income_employment",
    file_size_bytes: 1024,
    mime_type: "application/pdf",
    created_at: "2026-08-01T00:00:00Z",
    updated_at: "2026-08-01T00:00:00Z",
    ...(overrides as Partial<DocumentResponse>),
  } as DocumentResponse;
}

describe("ProcessingStrip (LP-UI-019)", () => {
  it("renders nothing when nothing is processing", () => {
    // An empty "Processing — 0 of 9" box is a permanent reminder of a thing
    // that is not happening.
    const { container } = render(<ProcessingStrip documents={[doc()]} />);
    expect(container.firstChild).toBeNull();
  });

  it("lists only the documents still in flight", () => {
    render(
      <ProcessingStrip
        documents={[
          doc({ id: "a", standard_name: "Settled W-2" }),
          doc({ id: "b", standard_name: "Arriving now", status: "extracting" }),
        ]}
      />,
    );
    expect(screen.getByText("Arriving now")).toBeTruthy();
    expect(screen.queryByText("Settled W-2")).toBeNull();
  });

  it("counts the in-flight documents against the whole file", () => {
    render(
      <ProcessingStrip
        documents={[
          doc({ id: "a" }),
          doc({ id: "b", status: "extracting" }),
          doc({ id: "c", status: "classifying" }),
        ]}
      />,
    );
    expect(screen.getByText("Processing — 2 of 3")).toBeTruthy();
  });

  it("names each document's stage rather than showing one spinner for all", () => {
    // "Classifying" and "Extracting" are different waits, and a processor
    // watching an upload land is asking which one they are in.
    render(
      <ProcessingStrip
        documents={[
          doc({ id: "b", standard_name: "One", status: "classified" }),
          doc({ id: "c", standard_name: "Two", status: "extracting" }),
        ]}
      />,
    );
    expect(screen.getByText("Classified")).toBeTruthy();
    expect(screen.getByText("Processing")).toBeTruthy();
  });

  it("falls back to the uploaded filename before a standard name exists", () => {
    // `standard_name` is typed `string`, not `string | null` — an unclassified
    // document carries the EMPTY one, which is the case this fallback is for.
    // An empty row is the one thing this strip must never show, and that is what
    // a bare `standard_name` would render here.
    render(
      <ProcessingStrip documents={[doc({ id: "b", standard_name: "", status: "pending" })]} />,
    );
    expect(screen.getByText("w2.pdf")).toBeTruthy();
  });
});
