import type { DocumentResponse, DocumentStatus } from "@/lib/types/document";
import { describe, expect, it } from "vitest";
import {
  MAX_STATUS_POLLS,
  POLL_INTERVAL_MS,
  SLOW_POLL_INTERVAL_MS,
  documentsRefetchInterval,
} from "./documents";

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
    processing_error: null,
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
    standard_name: "",
    period: null,
    package_qualification: { qualified: false, reason: "not_extracted" },
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

  it("SLOWS DOWN past the backstop rather than stopping (LP-637 review)", () => {
    // CHANGED DELIBERATELY, and the original intent is worth restating: a doc stuck PENDING (no
    // worker, dead pipeline) must not poll forever at full rate.
    //
    // Stopping outright was calibrated for one upload settling in a few polls. A bulk reprocess
    // legitimately runs for tens of minutes — the worker is serial and each document may take its
    // full 600s soft limit — so the hard stop froze the list mid-batch at "Pending", which is
    // exactly the "watching for documents to change, indistinguishable from a slow queue" failure
    // the reprocess toast copy exists to prevent. And because `dataUpdateCount` is cumulative for
    // the query's lifetime, a processor who had already watched an upload for two minutes got no
    // live polling for the batch at all.
    //
    // The primary stop is unchanged and still does the real work: nothing in progress, no polling
    // (asserted below). This only governs how often we ask while something genuinely is.
    const docs = [doc("pending")];
    expect(documentsRefetchInterval(docs, MAX_STATUS_POLLS + 1)).toBe(SLOW_POLL_INTERVAL_MS);
    expect(documentsRefetchInterval(docs, 9999)).toBe(SLOW_POLL_INTERVAL_MS);
    expect(SLOW_POLL_INTERVAL_MS).toBeGreaterThan(POLL_INTERVAL_MS);
  });

  it("still stops entirely once nothing is in progress, however many polls have run", () => {
    // The positive control for the change above: backing off must not become polling forever for
    // a file that has settled.
    expect(documentsRefetchInterval([doc("completed")], 9999)).toBe(false);
  });
});
