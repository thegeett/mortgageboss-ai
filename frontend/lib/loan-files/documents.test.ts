import {
  OVERRIDE_TYPE_OPTIONS,
  catchAllSections,
  extractionFields,
  extractionTransactions,
  formatFileSize,
  formatSource,
  groupDocumentsByCategory,
  hasInProgressDocuments,
  isTerminalStatus,
  maskLast4,
  maskSsn,
  otherCurrentSameType,
  stalenessBadge,
  supersededNote,
  typeReExtracts,
  validateUploadFile,
  versionLabel,
} from "@/lib/loan-files/documents";
import type { DocumentResponse, DocumentStatus, StalenessInfo } from "@/lib/types/document";
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
    tier: null,
    summary: null,
    classification_confidence: null,
    status: "pending",
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

describe("extractionFields (LP-39a typed core)", () => {
  it("reads {value, source}, orders known fields, formats money, nulls as —", () => {
    const fields = extractionFields({
      gross_pay: { value: "4200.00", source: { page: 1, snippet: "Gross 4,200.00" } },
      employer_name: { value: "ACME Corp", source: null },
      hours: { value: null, source: null },
    });
    // employer_name comes before gross_pay per the known order.
    expect(fields.map((f) => f.key)).toEqual(["employer_name", "gross_pay", "hours"]);
    const gross = fields.find((f) => f.key === "gross_pay");
    expect(gross?.value).toBe("$4,200.00");
    expect(gross?.source).toEqual({ page: 1, snippet: "Gross 4,200.00" });
    expect(fields.find((f) => f.key === "hours")?.value).toBe("—");
  });

  it("tolerates a bare value (no {value} wrapper)", () => {
    const fields = extractionFields({ employer_name: "ACME Corp" });
    expect(fields[0]?.value).toBe("ACME Corp");
    expect(fields[0]?.source).toBeNull();
  });

  it("masks the W-2 SSN and shows tax_year + boxes (LP-39b)", () => {
    const fields = extractionFields({
      tax_year: { value: 2024, source: null },
      employee_ssn: { value: "123-45-6789", source: { page: 1, snippet: "a 123-45-6789" } },
      wages_tips_other_comp: { value: "62000.00", source: null },
      additional_sections: [{ section: "State/Local", fields: [] }], // ignored here
    });
    const ssn = fields.find((f) => f.key === "employee_ssn");
    expect(ssn?.value).toBe("•••-••-6789"); // masked, never full
    expect(fields.find((f) => f.key === "tax_year")?.value).toBe("2024");
    expect(fields.find((f) => f.key === "wages_tips_other_comp")?.value).toBe("$62,000.00");
    expect(fields.some((f) => f.key === "additional_sections")).toBe(false);
  });
});

describe("maskSsn", () => {
  it("shows only the last 4, or — / ••• for empty/short", () => {
    expect(maskSsn("123-45-6789")).toBe("•••-••-6789");
    expect(maskSsn("123456789")).toBe("•••-••-6789");
    expect(maskSsn(null)).toBe("—");
    expect(maskSsn(undefined)).toBe("—");
    expect(maskSsn("12")).toBe("•••");
  });
});

describe("maskLast4 (account number, LP-39c)", () => {
  it("shows last 4, handling already-masked input", () => {
    expect(maskLast4("****1234")).toBe("••••1234");
    expect(maskLast4("000123456789")).toBe("••••6789");
    expect(maskLast4(null)).toBe("—");
  });
});

describe("extractionFields masks the account number (LP-39c)", () => {
  it("masks account_number_masked with last-4, not the SSN format", () => {
    const fields = extractionFields({
      account_number_masked: { value: "****1234", source: null },
      ending_balance: { value: "5230.18", source: null },
      transactions: [{ amount: "1" }], // excluded from typed-core rows
    });
    expect(fields.find((f) => f.key === "account_number_masked")?.value).toBe("••••1234");
    expect(fields.find((f) => f.key === "ending_balance")?.value).toBe("$5,230.18");
    expect(fields.some((f) => f.key === "transactions")).toBe(false);
  });
});

describe("extractionTransactions", () => {
  it("returns the transaction rows, ignoring non-objects/absent", () => {
    expect(
      extractionTransactions({
        transactions: [{ date: "2024-06-03", amount: "100" }, null, "nope"],
      }),
    ).toHaveLength(1);
    expect(extractionTransactions({ ending_balance: { value: "1" } })).toEqual([]);
  });
});

describe("catchAllSections", () => {
  it("returns the grouped sections, ignoring odd shapes", () => {
    const sections = catchAllSections({
      additional_sections: [
        { section: "Deductions", fields: [{ label: "401k", value: "210", source: null }] },
        { section: "Bad" }, // no fields array → filtered out
      ],
    });
    expect(sections.map((s) => s.section)).toEqual(["Deductions"]);
    expect(sections[0]?.fields[0]?.label).toBe("401k");
  });

  it("returns [] when absent", () => {
    expect(catchAllSections({ gross_pay: { value: "1" } })).toEqual([]);
  });
});

describe("formatSource", () => {
  it("formats page + snippet, or null when empty", () => {
    expect(formatSource({ page: 2, snippet: "Gross 4,200" })).toBe("p.2: “Gross 4,200”");
    expect(formatSource({ page: 3, snippet: null })).toBe("p.3");
    expect(formatSource(null)).toBeNull();
    expect(formatSource({ page: null, snippet: null })).toBeNull();
  });
});

describe("formatFileSize", () => {
  it("renders human sizes", () => {
    expect(formatFileSize(512)).toBe("512 B");
    expect(formatFileSize(1536)).toBe("1.5 KB");
    expect(formatFileSize(5 * 1024 * 1024)).toBe("5.0 MB");
  });
});

describe("typeReExtracts (LP-44 override hint)", () => {
  it("is true only for the extractable types", () => {
    expect(typeReExtracts("pay_stub")).toBe(true);
    expect(typeReExtracts("w2")).toBe(true);
    expect(typeReExtracts("bank_statement")).toBe(true);
  });

  it("is false for relabel-only / unknown / empty types", () => {
    expect(typeReExtracts("drivers_license")).toBe(false);
    expect(typeReExtracts("other")).toBe(false);
    expect(typeReExtracts(null)).toBe(false);
    expect(typeReExtracts(undefined)).toBe(false);
    expect(typeReExtracts("")).toBe(false);
  });

  it("offers the extractable types as selectable override options", () => {
    const values = OVERRIDE_TYPE_OPTIONS.map((o) => o.value);
    for (const t of ["pay_stub", "w2", "bank_statement"]) expect(values).toContain(t);
  });
});

// --- Versioning + staleness helpers (LP-71) -------------------------------- //

function staleness(overrides: Partial<StalenessInfo> = {}): StalenessInfo {
  return {
    is_stale: false,
    kind: null,
    reason: null,
    resolution: null,
    as_of_date: null,
    ...overrides,
  };
}

describe("stalenessBadge", () => {
  it("flags an aged document (warning-toned)", () => {
    const badge = stalenessBadge(doc({ staleness: staleness({ is_stale: true, kind: "aged" }) }));
    expect(badge?.label).toBe("May be stale");
    expect(badge?.className).toContain("warning");
  });

  it("flags an expired document", () => {
    const badge = stalenessBadge(
      doc({ staleness: staleness({ is_stale: true, kind: "expired" }) }),
    );
    expect(badge?.label).toBe("Expired");
  });

  it("shows a muted note once resolved", () => {
    const badge = stalenessBadge(doc({ staleness: staleness({ resolution: "waived" }) }));
    expect(badge?.label).toBe("Staleness waived");
    expect(badge?.className).toContain("gray");
  });

  it("is null for a fresh document", () => {
    expect(stalenessBadge(doc())).toBeNull();
  });
});

describe("versionLabel", () => {
  it("shows 'v2 of 2' for a multi-version document", () => {
    expect(versionLabel(doc({ version: 2, version_count: 2 }))).toBe("v2 of 2");
  });
  it("is null for a standalone document", () => {
    expect(versionLabel(doc({ version: 1, version_count: 1 }))).toBeNull();
  });
});

describe("supersededNote", () => {
  it("notes a historical document", () => {
    expect(supersededNote(doc({ is_current: false }))).toBe("Superseded by a newer version");
  });
  it("is null for the current version", () => {
    expect(supersededNote(doc({ is_current: true }))).toBeNull();
  });
});

describe("otherCurrentSameType", () => {
  it("finds other current documents of the same type (gentle duplicate surfacing)", () => {
    const a = doc({ id: "a", document_type: "pay_stub" });
    const b = doc({ id: "b", document_type: "pay_stub" });
    const c = doc({ id: "c", document_type: "w2" });
    const historical = doc({ id: "d", document_type: "pay_stub", is_current: false });
    const all = [a, b, c, historical];
    expect(otherCurrentSameType(a, all).map((d) => d.id)).toEqual(["b"]); // not c (type), not d (historical)
  });

  it("returns none for a historical document", () => {
    const a = doc({ id: "a", document_type: "pay_stub", is_current: false });
    const b = doc({ id: "b", document_type: "pay_stub" });
    expect(otherCurrentSameType(a, [a, b])).toEqual([]);
  });
});
