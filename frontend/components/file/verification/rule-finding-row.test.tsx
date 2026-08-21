// @vitest-environment jsdom
import type { RuleFinding } from "@/lib/types/verification";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { RuleFindingRow } from "./rule-finding-row";

afterEach(cleanup);

function finding(overrides: Partial<RuleFinding> = {}): RuleFinding {
  return {
    id: "f1",
    rule_id: "ID-4",
    rule_name: "Current address consistency",
    missing_documents: [],
    can_apply: false,
    evaluation_outcome: "open",
    status: "red",
    category: "Identity",
    message: "the current residence address varies across sources",
    subject_key: "b1",
    subject_label: "Aditya Talluri",
    guideline: null,
    load_bearing_tags: [],
    ratification_pending: false,
    how_to_fix: null,
    confidence: 1,
    resolution_status: "open",
    source_documents: [],
    ...overrides,
  };
}

/** The provenance lives in the expander, so open it the way a processor would. */
function renderExpanded(f: RuleFinding, fileId?: string) {
  render(<RuleFindingRow finding={f} fileId={fileId} />);
  const [expander] = screen.getAllByRole("button");
  if (!expander) throw new Error("the row has no expander to open");
  fireEvent.click(expander);
}

describe("LP-617 — a finding names the documents it is about", () => {
  it("lists each source document, linking to the document itself", () => {
    renderExpanded(
      finding({
        source_documents: [
          { id: "doc-a", filename: "W2-2023.pdf" },
          { id: "doc-b", filename: "paystub-april.pdf" },
        ],
      }),
      "LF-3CVT",
    );

    expect(screen.getByRole("link", { name: "W2-2023.pdf" }).getAttribute("href")).toBe(
      "/loan-files/LF-3CVT/documents?doc=doc-a",
    );
    expect(screen.getByRole("link", { name: "paystub-april.pdf" }).getAttribute("href")).toBe(
      "/loan-files/LF-3CVT/documents?doc=doc-b",
    );
    expect(screen.getByText(/Documents:/)).toBeDefined();
  });

  it("says 'Document' rather than 'Documents' for a single source", () => {
    renderExpanded(
      finding({ source_documents: [{ id: "doc-a", filename: "W2-2023.pdf" }] }),
      "LF-3CVT",
    );
    expect(screen.getByText(/Document:/)).toBeDefined();
  });

  it("renders nothing when the finding has no documents — honest, not missing", () => {
    // A loan-level rule over a computed value (DTI, reserves, LTV) has none to point at, and a
    // fabricated link is worse than no link.
    renderExpanded(finding({ source_documents: [] }), "LF-3CVT");
    expect(screen.queryByText(/Documents?:/)).toBeNull();
  });

  it("names the document without a link when there is no file to link into", () => {
    renderExpanded(finding({ source_documents: [{ id: "doc-a", filename: "W2-2023.pdf" }] }));
    expect(screen.queryByRole("link", { name: "W2-2023.pdf" })).toBeNull();
    expect(screen.getByText("W2-2023.pdf")).toBeDefined();
  });
});
