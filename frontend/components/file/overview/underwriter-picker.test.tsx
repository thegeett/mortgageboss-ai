// @vitest-environment jsdom
/**
 * LP-813 — the underwriter row, and the three states it must tell apart.
 *
 * Each is a different sentence to a processor, and merging any two of them says something false:
 *
 *   no lender          there is nothing to choose from yet — not "no underwriters exist"
 *   nobody assigned    a real, ordinary state
 *   assigned but gone  the file names someone this lender's list no longer contains
 *
 * The third is the one that would be got wrong. A picker that resolves the name from the contacts
 * list and falls back to "Not assigned" when it misses would tell a processor the field is empty
 * when it is not — and the fix is to notice that the ID is set and the NAME is missing, which are
 * different facts.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

const mockAssign = vi.fn();
const mockContacts = vi.fn();

vi.mock("@/lib/api/lenders", () => ({
  useLenderContacts: (...args: unknown[]) => mockContacts(...args),
  useSetUnderwriter: () => ({ mutate: mockAssign, isPending: false }),
}));

vi.mock("@/lib/toast", () => ({ notifySuccess: vi.fn(), notifyError: vi.fn() }));

import { type UnderwriterFile, UnderwriterPicker } from "./underwriter-picker";

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const DANA = {
  id: "contact-1",
  lender_id: "lender-1",
  name: "Dana Reed",
  email: "dana@uwm.example.com",
  phone: null,
  role: "underwriter" as const,
  notes: null,
  is_active: true,
};

// Exactly the component's own prop type — NOT a cast partial of `LoanFileDetail`. The component
// declares the three fields it reads, so a fourth one added later is a type error here rather than
// an `undefined` these cases never notice.
const FILE: UnderwriterFile = {
  id: "file-1",
  lender_id: "lender-1",
  underwriter_contact_id: null,
};

const render_ = (file: UnderwriterFile) => render(<UnderwriterPicker file={file} />, { wrapper });

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("before a lender is chosen", () => {
  it("says there is nothing to choose from rather than showing an empty picker", () => {
    // An empty dropdown reads as "this lender has no underwriters", which is a different and wrong
    // fact — the lender has not been chosen at all.
    mockContacts.mockReturnValue({ data: [], isPending: false });

    render_({ ...FILE, lender_id: null });

    expect(screen.getByText(/Choose a target lender first/)).toBeDefined();
    expect(screen.queryByRole("button", { name: "Assign" })).toBeNull();
  });

  it("does not ask the server for contacts it cannot scope", () => {
    mockContacts.mockReturnValue({ data: [], isPending: false });
    render_({ ...FILE, lender_id: null });
    expect(mockContacts).toHaveBeenCalledWith(null);
  });
});

describe("with a lender", () => {
  it("shows nobody assigned, and offers to assign", () => {
    mockContacts.mockReturnValue({ data: [DANA], isPending: false });

    render_(FILE);

    expect(screen.getByText("Not assigned")).toBeDefined();
    expect(screen.getByRole("button", { name: "Assign" })).toBeDefined();
  });

  it("shows the assigned underwriter by name and address", () => {
    mockContacts.mockReturnValue({ data: [DANA], isPending: false });

    render_({ ...FILE, underwriter_contact_id: DANA.id });

    expect(screen.getByText(/Dana Reed/)).toBeDefined();
    expect(screen.getByText(/dana@uwm.example.com/)).toBeDefined();
    expect(screen.getByRole("button", { name: "Change" })).toBeDefined();
  });

  it("does not call an assigned-but-departed contact 'Not assigned'", () => {
    // THE ONE THAT WOULD BE GOT WRONG. The id is set and the name is missing; those are different
    // facts, and reporting the field as empty would hide that the file still names somebody.
    mockContacts.mockReturnValue({ data: [], isPending: false });

    render_({ ...FILE, underwriter_contact_id: "someone-removed" });

    expect(screen.queryByText("Not assigned")).toBeNull();
    expect(screen.getByText(/No longer at this lender/)).toBeDefined();
  });

  it("says the lender has no contacts rather than offering an empty list", () => {
    mockContacts.mockReturnValue({ data: [], isPending: false });
    render_(FILE);

    fireEvent.click(screen.getByRole("button", { name: "Assign" }));

    expect(screen.getByText(/No contacts are set up for this lender yet/)).toBeDefined();
    expect(screen.queryByRole("combobox")).toBeNull();
  });

  it("assigns the chosen contact", () => {
    mockContacts.mockReturnValue({ data: [DANA], isPending: false });
    render_(FILE);
    fireEvent.click(screen.getByRole("button", { name: "Assign" }));

    fireEvent.change(screen.getByRole("combobox"), { target: { value: DANA.id } });

    expect(mockAssign).toHaveBeenCalledWith(DANA.id, expect.anything());
  });

  it("clears with null rather than an empty string", () => {
    // The endpoint takes `contact_id: null` to clear. An empty string is a malformed uuid and would
    // come back a 422 — which the processor would read as "clearing is broken".
    mockContacts.mockReturnValue({ data: [DANA], isPending: false });
    render_({ ...FILE, underwriter_contact_id: DANA.id });
    fireEvent.click(screen.getByRole("button", { name: "Change" }));

    fireEvent.change(screen.getByRole("combobox"), { target: { value: "" } });

    expect(mockAssign).toHaveBeenCalledWith(null, expect.anything());
  });

  it("does not offer an inactive contact", () => {
    mockContacts.mockReturnValue({
      data: [DANA, { ...DANA, id: "contact-2", name: "Gone Person", is_active: false }],
      isPending: false,
    });
    render_(FILE);
    fireEvent.click(screen.getByRole("button", { name: "Assign" }));

    expect(screen.getByRole("option", { name: /Dana Reed/ })).toBeDefined();
    expect(screen.queryByRole("option", { name: /Gone Person/ })).toBeNull();
  });
});
