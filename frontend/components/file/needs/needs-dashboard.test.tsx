// @vitest-environment jsdom
import type { NeedsItemPublic } from "@/lib/types/needs-item";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// The dashboard fetches via hooks; mock the two data layers it depends on so the
// test drives the data and asserts the rendered checklist + the disposition wiring.
const { confirmMutate } = vi.hoisted(() => ({ confirmMutate: vi.fn() }));

const useNeeds = vi.fn();
const useLoanFileDocuments = vi.fn();
const useLoanFile = vi.fn();

vi.mock("@/lib/api/needs", () => ({
  useNeeds: (...args: unknown[]) => useNeeds(...args),
  useConfirmNeed: () => ({ mutate: confirmMutate, isPending: false }),
  useAdjustNeed: () => ({ mutate: vi.fn(), isPending: false }),
  useDismissNeed: () => ({ mutate: vi.fn(), isPending: false }),
  useWaiveNeed: () => ({ mutate: vi.fn(), isPending: false }),
  useAddNeed: () => ({ mutate: vi.fn(), isPending: false }),
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
