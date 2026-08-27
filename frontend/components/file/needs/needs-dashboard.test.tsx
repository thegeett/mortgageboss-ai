// @vitest-environment jsdom
import type { NeedsItemPublic } from "@/lib/types/needs-item";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// The dashboard fetches via hooks; mock the two data layers it depends on so the
// test drives the data and asserts the rendered checklist + the disposition wiring.
const {
  confirmMutate,
  coverageMutate,
  mergeMutate,
  keepBothMutate,
  dismissMutate,
  notCoveredMutate,
} = vi.hoisted(() => ({
  confirmMutate: vi.fn(),
  coverageMutate: vi.fn(),
  mergeMutate: vi.fn(),
  keepBothMutate: vi.fn(),
  dismissMutate: vi.fn(),
  notCoveredMutate: vi.fn(),
}));

const useNeeds = vi.fn();
const useLoanFileDocuments = vi.fn();
const useLoanFile = vi.fn();

vi.mock("@/lib/api/needs", () => ({
  useNeeds: (...args: unknown[]) => useNeeds(...args),
  useConfirmNeed: () => ({ mutate: confirmMutate, isPending: false }),
  useConfirmCoverage: () => ({ mutate: coverageMutate, isPending: false }),
  useAdjustNeed: () => ({ mutate: vi.fn(), isPending: false }),
  useDismissNeed: () => ({ mutate: dismissMutate, isPending: false }),
  useWaiveNeed: () => ({ mutate: vi.fn(), isPending: false }),
  useAddNeed: () => ({ mutate: vi.fn(), isPending: false }),
  useMergeDuplicate: () => ({ mutate: mergeMutate, isPending: false }),
  useNotDuplicate: () => ({ mutate: keepBothMutate, isPending: false }),
  useNotCovered: () => ({ mutate: notCoveredMutate, isPending: false }),
}));

vi.mock("@/lib/api/documents", () => ({
  useLoanFileDocuments: (...args: unknown[]) => useLoanFileDocuments(...args),
}));

vi.mock("@/lib/api/loan-files", () => ({
  useLoanFile: (...args: unknown[]) => useLoanFile(...args),
}));

import { NeedsDashboard } from "./needs-dashboard";

function need(overrides: Partial<NeedsItemPublic> = {}): NeedsItemPublic {
  return {
    id: "n1",
    title: "Two years of tax returns",
    description: null,
    category: "income_employment",
    needs_type: "tax_return",
    status: "pending",
    priority: "standard",
    origin: "ai_reasoning",
    disposition: "proposed",
    reasoning: "Self-employment income from Chhotala Realty LLC is qualified from tax returns.",
    reason: null,
    borrower_id: null,
    satisfied_by_document_id: null,
    satisfied_by_document_filename: null,
    satisfied_at: null,
    requires_coverage_confirmation: false,
    matching_documents: [],
    source: null,
    possible_duplicate_of: null,
    possibly_covered_by: null,
    coverage_note: null,
    created_at: "2026-06-19T12:00:00Z",
    ...overrides,
  };
}

function setDocuments(inProgress: boolean) {
  useLoanFileDocuments.mockReturnValue({
    data: inProgress ? [{ status: "pending" }] : [],
  });
}

function setNeeds(state: Record<string, unknown>) {
  useNeeds.mockReturnValue({
    data: undefined,
    isPending: false,
    isError: false,
    isFetching: false,
    refetch: vi.fn(),
    ...state,
  });
}

function setAiStatus(status: "pending" | "completed" | "failed" | null) {
  useLoanFile.mockReturnValue({ data: status === null ? {} : { ai_needs_status: status } });
}

beforeEach(() => {
  // Default: no AI-needs note (settled/not-triggered). Tests override via setAiStatus.
  useLoanFile.mockReturnValue({ data: { ai_needs_status: null } });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("NeedsDashboard", () => {
  it("shows a loading cue while pending", () => {
    setDocuments(false);
    setNeeds({ isPending: true });
    const { container } = render(<NeedsDashboard fileId="f1" />);
    expect(screen.getByText("Loading the needs list")).toBeDefined();
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
  });

  it("shows the empty state with no needs", () => {
    setDocuments(false);
    setNeeds({ data: [] });
    render(<NeedsDashboard fileId="f1" />);
    expect(screen.getByText("No needs yet")).toBeDefined();
  });

  it("shows an error state", () => {
    setDocuments(false);
    setNeeds({ isError: true });
    render(<NeedsDashboard fileId="f1" />);
    expect(screen.getByText("Couldn't load the needs list.")).toBeDefined();
  });

  it("renders the need, its state, source tag, and the AI reasoning (the 'why')", () => {
    setDocuments(false);
    setNeeds({ data: [need()] });
    render(<NeedsDashboard fileId="f1" />);
    expect(screen.getByText("Two years of tax returns")).toBeDefined();
    expect(screen.getByText("Needs action")).toBeDefined(); // the action-oriented group
    expect(screen.getByText("Pending")).toBeDefined(); // the visual state
    expect(screen.getByText("AI")).toBeDefined(); // the provenance tag
    // The reasoning is surfaced — explainability made visible.
    expect(screen.getByText(/Self-employment income from Chhotala Realty LLC/)).toBeDefined();
  });

  it("offers Confirm on a proposed need and calls the API when clicked", () => {
    setDocuments(false);
    setNeeds({ data: [need()] });
    render(<NeedsDashboard fileId="f1" />);
    const confirm = screen.getByRole("button", { name: "Confirm" });
    fireEvent.click(confirm);
    expect(confirmMutate).toHaveBeenCalledWith("n1", expect.anything());
  });

  // LP-108 — honest satisfaction: a graded need with a document attached (received) shows
  // "Confirm coverage" (not a false "satisfied"), the honest coverage note, and the matched doc.
  it("shows 'confirm coverage' + the attached document for a graded received need", () => {
    setDocuments(false);
    setNeeds({
      data: [
        need({
          status: "received",
          requires_coverage_confirmation: true,
          satisfied_by_document_filename: "BofA checking April.pdf",
        }),
      ],
    });
    render(<NeedsDashboard fileId="f1" />);
    expect(screen.getByText("Documents attached")).toBeDefined(); // honest status pill, not "Verified"
    expect(screen.queryByText("Verified")).toBeNull(); // never a false-green
    expect(screen.getByText(/confirm this covers the full requirement/i)).toBeDefined(); // honest note
    expect(screen.getByText("BofA checking April.pdf")).toBeDefined(); // the matched document shown

    fireEvent.click(screen.getByRole("button", { name: /confirm coverage/i }));
    expect(coverageMutate).toHaveBeenCalledWith("n1", expect.anything());
  });

  // LP-109 — derive-on-read: a graded need shows ALL matching documents (name each), including the
  // intentionally coarse/over-inclusive match, so the processor confirms coverage against the full set.
  it("shows ALL matching documents for a graded need (derive-on-read)", () => {
    setDocuments(false);
    setNeeds({
      data: [
        need({
          status: "received",
          requires_coverage_confirmation: true,
          satisfied_by_document_filename: "BofA checking April.pdf", // the trigger
          matching_documents: [
            { id: "d1", filename: "BofA checking April.pdf" },
            { id: "d2", filename: "BofA savings May.pdf" },
            { id: "d3", filename: "EMD Withdrawal.pdf" }, // intentionally over-inclusive, shown as-is
          ],
        }),
      ],
    });
    render(<NeedsDashboard fileId="f1" />);
    expect(screen.getByText("3 matching documents")).toBeDefined(); // the full set, not just one
    expect(screen.getByText("BofA savings May.pdf")).toBeDefined();
    expect(screen.getByText("EMD Withdrawal.pdf")).toBeDefined(); // coarse match shown as-is (not narrowed)
    expect(screen.queryByText("Verified")).toBeNull(); // LP-108 status untouched — not a false-green
  });

  // LP-110 — every need shows its SOURCE, honestly attributed by origin. A deterministic floor
  // source reads as certain; an AI-identified source is marked "verify" and grounds to the fact(s)
  // the AI cited. The two are visually/semantically distinct — an AI reading is never shown as fact.
  it("shows a deterministic floor need's source as a certain rule", () => {
    setDocuments(false);
    setNeeds({
      data: [
        need({
          origin: "floor",
          disposition: "confirmed",
          needs_type: "pay_stub",
          source: {
            attribution: "deterministic",
            facts: [
              {
                kind: "income",
                label: "Employment income is stated on the application",
                ref: null,
                document_id: null,
                document_filename: null,
              },
            ],
          },
        }),
      ],
    });
    render(<NeedsDashboard fileId="f1" />);
    expect(screen.getByText("deterministic rule")).toBeDefined(); // certain — a rule
    expect(screen.getByText("Employment income is stated on the application")).toBeDefined();
    expect(screen.queryByText(/AI-identified — verify/i)).toBeNull(); // not the AI's reading
  });

  it("marks an AI-reasoned need's source as AI-identified (verify), grounded to the cited fact", () => {
    setDocuments(false);
    setNeeds({
      data: [
        need({
          origin: "ai_reasoning",
          source: {
            attribution: "ai_identified",
            facts: [
              {
                kind: "employer",
                label: "Self-employment income from Chhotala Realty LLC",
                ref: null,
                document_id: null,
                document_filename: null,
              },
            ],
          },
        }),
      ],
    });
    render(<NeedsDashboard fileId="f1" />);
    expect(screen.getByText("AI-identified")).toBeDefined(); // the trust pill — the AI's reading
    expect(screen.getByText("Self-employment income from Chhotala Realty LLC")).toBeDefined();
    expect(screen.getByText(/verify this is the right triggering fact/i)).toBeDefined(); // verify note
  });

  it("surfaces a suggestion need's finding chain, linking the source document", () => {
    setDocuments(false);
    setNeeds({
      data: [
        need({
          origin: "suggestion",
          source: {
            attribution: "finding",
            facts: [
              {
                kind: "finding",
                label: "Monthly child support obligation of $1,200",
                ref: "finding-1",
                document_id: "doc-1",
                document_filename: "Divorce Decree.pdf",
              },
            ],
          },
        }),
      ],
    });
    render(<NeedsDashboard fileId="f1" />);
    expect(screen.getByText("finding")).toBeDefined(); // the finding attribution pill
    expect(screen.getByText("Monthly child support obligation of $1,200")).toBeDefined();
    expect(screen.getByText("Divorce Decree.pdf")).toBeDefined(); // grounded to the source document
  });

  // LP-111 — the AI-flagged possible-duplicate surfaces a Merge / Keep-both prompt (never a silent
  // merge); the processor disposes.
  it("shows a possible-duplicate flag with merge / keep-both actions", () => {
    setDocuments(false);
    setNeeds({ data: [need({ possible_duplicate_of: "other-need-id" })] });
    render(<NeedsDashboard fileId="f1" />);
    expect(screen.getByText(/possible duplicate/i)).toBeDefined();

    fireEvent.click(screen.getByRole("button", { name: "Merge" }));
    expect(mergeMutate).toHaveBeenCalledWith("n1", expect.anything());

    fireEvent.click(screen.getByRole("button", { name: /keep both/i }));
    expect(keepBothMutate).toHaveBeenCalledWith("n1", expect.anything());
  });

  // LP-631 — a coverage predicate concluded the file already answers the need. It FLAGS (ADR-388):
  // the note carries the WHY, and the processor either dismisses the need or keeps it.
  it("shows a coverage flag with its reasoning and dismiss / keep actions", () => {
    setDocuments(false);
    setNeeds({
      data: [
        need({
          possibly_covered_by: { id: "d9", filename: "credit-report.pdf" },
          coverage_note:
            "The credit report lists ALLY FINANCIAL at $438/mo, matching the stated leasepayment liability on the application.",
        }),
      ],
    });
    render(<NeedsDashboard fileId="f1" />);
    expect(screen.getByText(/may already answer this/i)).toBeDefined();
    expect(screen.getByText(/ALLY FINANCIAL at \$438\/mo/)).toBeDefined();
    expect(screen.getByText("credit-report.pdf")).toBeDefined();

    fireEvent.click(screen.getByRole("button", { name: /dismiss need/i }));
    expect(dismissMutate).toHaveBeenCalledWith({ needId: "n1" }, expect.anything());

    fireEvent.click(screen.getByRole("button", { name: /keep it/i }));
    expect(notCoveredMutate).toHaveBeenCalledWith("n1", expect.anything());
  });

  it("shows no coverage flag when nothing flagged the need", () => {
    setDocuments(false);
    setNeeds({ data: [need()] });
    render(<NeedsDashboard fileId="f1" />);
    expect(screen.queryByText(/may already answer this/i)).toBeNull();
  });

  it("shows no duplicate flag when the need isn't flagged", () => {
    setDocuments(false);
    setNeeds({ data: [need()] });
    render(<NeedsDashboard fileId="f1" />);
    expect(screen.queryByText(/possible duplicate/i)).toBeNull();
  });

  it("shows 'satisfied by' the document for a verified simple-presence need", () => {
    setDocuments(false);
    setNeeds({
      data: [
        need({
          status: "verified",
          needs_type: "drivers_license",
          requires_coverage_confirmation: false,
          satisfied_by_document_filename: "license.pdf",
        }),
      ],
    });
    render(<NeedsDashboard fileId="f1" />);
    expect(screen.getByText("Verified")).toBeDefined();
    expect(screen.getByText("license.pdf")).toBeDefined(); // the matched document is shown
  });

  it("does not offer Confirm once a need is confirmed", () => {
    setDocuments(false);
    setNeeds({ data: [need({ disposition: "confirmed" })] });
    render(<NeedsDashboard fileId="f1" />);
    expect(screen.queryByRole("button", { name: "Confirm" })).toBeNull();
  });

  it("shows the subtle 'Updating…' cue while documents are processing", () => {
    setDocuments(true); // a document is in flight
    setNeeds({ data: [need({ disposition: "confirmed" })] });
    render(<NeedsDashboard fileId="f1" />);
    expect(screen.getByText("Updating…")).toBeDefined();
  });

  it("hides the 'Updating…' cue when settled", () => {
    setDocuments(false);
    setNeeds({ data: [need({ disposition: "confirmed" })] });
    render(<NeedsDashboard fileId="f1" />);
    expect(screen.queryByText("Updating…")).toBeNull();
  });

  it("groups a verified need under Complete and names its satisfying document", () => {
    setDocuments(false);
    setNeeds({
      data: [
        need({
          id: "n2",
          status: "verified",
          disposition: "confirmed",
          satisfied_by_document_filename: "tax_return_2023.pdf",
        }),
      ],
    });
    render(<NeedsDashboard fileId="f1" />);
    expect(screen.getByText("Complete")).toBeDefined();
    expect(screen.getByText(/tax_return_2023\.pdf/)).toBeDefined();
  });

  // LP-71.5 — the AI-needs reasoning note (no silent floor-only-as-complete)

  it("notes that more needs may appear while AI reasoning is pending", () => {
    setDocuments(false);
    setNeeds({
      data: [need({ origin: "floor", disposition: "confirmed", needs_type: "pay_stub" })],
    });
    setAiStatus("pending");
    render(<NeedsDashboard fileId="f1" />);
    expect(screen.getByText(/more needs may appear/i)).toBeDefined();
  });

  it("warns that the list may be incomplete when AI reasoning failed", () => {
    setDocuments(false);
    setNeeds({
      data: [need({ origin: "floor", disposition: "confirmed", needs_type: "pay_stub" })],
    });
    setAiStatus("failed");
    render(<NeedsDashboard fileId="f1" />);
    expect(screen.getByText(/may be incomplete/i)).toBeDefined();
  });

  it("shows no AI note once reasoning is complete", () => {
    setDocuments(false);
    setNeeds({ data: [need()] });
    setAiStatus("completed");
    render(<NeedsDashboard fileId="f1" />);
    expect(screen.queryByText(/more needs may appear/i)).toBeNull();
    expect(screen.queryByText(/may be incomplete/i)).toBeNull();
  });
});
