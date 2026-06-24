import type { DocumentResponse, DocumentStatus } from "@/lib/types/document";
import { describe, expect, it } from "vitest";
import { MAX_STATUS_POLLS, POLL_INTERVAL_MS, documentsRefetchInterval } from "./documents";

function doc(status: DocumentStatus): DocumentResponse {
  return {
    id: Math.random().toString(36).slice(2),
    loan_file_id: "f1",
    original_filename: "x.pdf",
    mime_type: "application/pdf",
    file_size_bytes: 10,
    document_type: null,
    category: null,
    tier: null,
    summary: null,
    classification_confidence: null,
    status,
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
  };
}

describe("documentsRefetchInterval — live polling + backstop", () => {
  it("does not poll before any data has loaded", () => {
    expect(documentsRefetchInterval(undefined, 0)).toBe(false);
  });

  it("does not poll when every document is terminal", () => {
    const docs = [doc("completed"), doc("needs_review"), doc("failed")];
    expect(documentsRefetchInterval(docs, 1)).toBe(false);
  });

  it("polls while a document is still in-progress (under the backstop)", () => {
    const docs = [doc("completed"), doc("pending")];
    expect(documentsRefetchInterval(docs, 1)).toBe(POLL_INTERVAL_MS);
    expect(documentsRefetchInterval(docs, MAX_STATUS_POLLS)).toBe(POLL_INTERVAL_MS);
  });

  it("STOPS polling a stuck in-progress doc once the backstop is exceeded", () => {
    // A doc stuck PENDING (no worker / dead pipeline) must not poll forever.
    const docs = [doc("pending")];
    expect(documentsRefetchInterval(docs, MAX_STATUS_POLLS + 1)).toBe(false);
    expect(documentsRefetchInterval(docs, 9999)).toBe(false);
  });
});
