import {
  extractionFields,
  formatFileSize,
  groupDocumentsByCategory,
  hasInProgressDocuments,
  isTerminalStatus,
  validateUploadFile,
} from "@/lib/loan-files/documents";
import type { DocumentResponse, DocumentStatus } from "@/lib/types/document";
import { describe, expect, it } from "vitest";

function doc(overrides: Partial<DocumentResponse> = {}): DocumentResponse {
  return {
    id: Math.random().toString(36).slice(2),
    loan_file_id: "f1",
    original_filename: "paystub.pdf",
    mime_type: "application/pdf",
    file_size_bytes: 1024,
    document_type: null,
    category: null,
    classification_confidence: null,
    status: "pending",
    upload_source: "user_upload",
    uploaded_by_user_id: "u1",
    created_at: "2026-06-12T10:00:00Z",
    updated_at: "2026-06-12T10:00:00Z",
    ...overrides,
  };
}

describe("isTerminalStatus / polling", () => {
  it("treats pipeline-active statuses as non-terminal", () => {
    const inProgress: DocumentStatus[] = ["pending", "classifying", "classified", "extracting"];
    for (const s of inProgress) expect(isTerminalStatus(s)).toBe(false);
  });

  it("treats settled statuses as terminal", () => {
    const terminal: DocumentStatus[] = ["completed", "needs_review", "failed"];
    for (const s of terminal) expect(isTerminalStatus(s)).toBe(true);
  });

  it("polls while ANY document is in-progress", () => {
    expect(hasInProgressDocuments([doc({ status: "completed" }), doc({ status: "pending" })])).toBe(
      true,
    );
  });

  it("stops once ALL documents are terminal", () => {
    expect(
      hasInProgressDocuments([
        doc({ status: "completed" }),
        doc({ status: "needs_review" }),
        doc({ status: "failed" }),
      ]),
    ).toBe(false);
  });

  it("does not poll an empty list", () => {
    expect(hasInProgressDocuments([])).toBe(false);
  });
});

describe("groupDocumentsByCategory", () => {
  it("groups by category and buckets uncategorized last", () => {
    const groups = groupDocumentsByCategory([
      doc({ id: "a", category: "income_employment" }),
      doc({ id: "b", category: null, status: "pending" }),
      doc({ id: "c", category: "assets" }),
    ]);
    const keys = groups.map((g) => g.key);
    expect(keys).toEqual(["income_employment", "assets", "uncategorized"]);
    expect(groups.at(-1)?.label).toMatch(/uncategorized/i);
  });

  it("orders documents newest-first within a group", () => {
    const groups = groupDocumentsByCategory([
      doc({ id: "old", category: "assets", created_at: "2026-06-01T00:00:00Z" }),
      doc({ id: "new", category: "assets", created_at: "2026-06-12T00:00:00Z" }),
    ]);
    expect(groups[0]?.documents.map((d) => d.id)).toEqual(["new", "old"]);
  });
});

describe("validateUploadFile", () => {
  const make = (name: string, type: string, size: number) => ({ name, type, size }) as File;

  it("accepts PDF/JPG/PNG within the size limit", () => {
    expect(validateUploadFile(make("a.pdf", "application/pdf", 1000))).toBeNull();
    expect(validateUploadFile(make("a.png", "image/png", 1000))).toBeNull();
    expect(validateUploadFile(make("a.jpg", "image/jpeg", 1000))).toBeNull();
  });

  it("rejects unsupported types", () => {
    const err = validateUploadFile(make("a.txt", "text/plain", 1000));
    expect(err?.reason).toMatch(/unsupported/i);
  });

  it("rejects files over 50 MB", () => {
    const err = validateUploadFile(make("big.pdf", "application/pdf", 51 * 1024 * 1024));
    expect(err?.reason).toMatch(/50 MB/i);
  });
});

describe("extractionFields", () => {
  it("orders known pay-stub fields, formats money, and renders nulls as —", () => {
    const fields = extractionFields({
      gross_pay: "4200.00",
      employer_name: "ACME Corp",
      hours: null,
    });
    // employer_name comes before gross_pay per the known order.
    expect(fields.map((f) => f.key)).toEqual(["employer_name", "gross_pay", "hours"]);
    expect(fields.find((f) => f.key === "gross_pay")?.value).toBe("$4,200.00");
    expect(fields.find((f) => f.key === "hours")?.value).toBe("—");
  });

  it("includes unknown keys after the known ones", () => {
    const fields = extractionFields({ custom_field: "x", gross_pay: "100" });
    expect(fields[0]?.key).toBe("gross_pay");
    expect(fields.some((f) => f.key === "custom_field")).toBe(true);
  });
});

describe("formatFileSize", () => {
  it("renders human sizes", () => {
    expect(formatFileSize(512)).toBe("512 B");
    expect(formatFileSize(1536)).toBe("1.5 KB");
    expect(formatFileSize(5 * 1024 * 1024)).toBe("5.0 MB");
  });
});
