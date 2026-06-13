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
    classification_confidence: 0.9,
    status: "completed",
    upload_source: "user_upload",
    uploaded_by_user_id: "u1",
    created_at: "2026-06-12T10:00:00Z",
    updated_at: "2026-06-12T10:00:00Z",
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
