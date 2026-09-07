// @vitest-environment jsdom
/**
 * LP-820 — the panel, and the row it must not hide.
 *
 * A SCREEN THAT SHOWED ONLY WHAT IT COULD SEND would render a file with five outstanding title
 * documents as having nothing to do — which is the build plan's "sit at PENDING forever, invisible
 * to LP-814", rendered. So the unreachable party gets a row that names what is stuck and a field
 * that unsticks it.
 *
 * AND "BUILD REQUEST" MUST NOT READ AS SENDING. The draft goes out through LP-811a's send path with
 * its rate limit and suppression check; a button here saying "Send" would be the one outbound
 * message in the product that skipped that gate.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

const mockRequests = vi.fn();
const mockAdd = vi.fn();
const mockBuild = vi.fn();

vi.mock("@/lib/api/party-requests", () => ({
  usePartyRequests: () => mockRequests(),
  useAddPartyAddress: () => ({ mutate: mockAdd, isPending: false }),
  useBuildPartyDraft: () => ({ mutate: mockBuild, isPending: false }),
}));
vi.mock("@/lib/toast", () => ({ notifySuccess: vi.fn(), notifyError: vi.fn() }));

import type { PartyRequest } from "@/lib/types/party-request";
import { PartyRequestsPanel } from "./party-requests-panel";

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const UNREACHABLE: PartyRequest = {
  party: "title",
  role: "title",
  address: null,
  name: null,
  reachable: false,
  needs: [{ id: "n1", title: "Title commitment" }],
};

/** The one party whose participant ROLE differs from its name — `lender` → `underwriter`. */
const LENDER_UNREACHABLE: PartyRequest = {
  party: "lender",
  role: "underwriter",
  address: null,
  name: null,
  reachable: false,
  needs: [{ id: "n3", title: "Conditional approval" }],
};

const REACHABLE: PartyRequest = {
  party: "cpa",
  role: "cpa",
  address: "books@cpa.example",
  name: "Books LLP",
  reachable: true,
  needs: [{ id: "n2", title: "CPA letter" }],
};

function loaded(data: PartyRequest[]) {
  mockRequests.mockReturnValue({ data, isPending: false, isError: false });
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("a party with no address", () => {
  it("is shown, with what is stuck and how to unstick it", () => {
    loaded([UNREACHABLE]);
    render(<PartyRequestsPanel fileId="f1" />, { wrapper });

    expect(screen.getByText("Title company")).toBeDefined();
    expect(screen.getByText("Title commitment")).toBeDefined();
    expect(screen.getByText(/No address yet/)).toBeDefined();
    expect(screen.getByRole("button", { name: "Save address" })).toBeDefined();
  });

  it("is not offered a request it cannot send", () => {
    loaded([UNREACHABLE]);
    render(<PartyRequestsPanel fileId="f1" />, { wrapper });

    expect(screen.queryByRole("button", { name: "Build request" })).toBeNull();
  });

  it("saves the address against the SERVER'S role, not the party name", () => {
    // A LENDER, because that is the only party whose role differs from its name — `lender` maps to
    // the `underwriter` participant role (LP-813). Measured: with a title fixture, where the two
    // strings are identical, sending the party instead of the role passes the test unchanged.
    //
    // The distinction is real: two parties can share a mailbox, and the role is what decides which
    // request the address answers.
    loaded([LENDER_UNREACHABLE]);
    render(<PartyRequestsPanel fileId="f1" />, { wrapper });

    fireEvent.change(screen.getByLabelText(/Lender's email/), {
      target: { value: " uw@lender.example " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save address" }));

    expect(mockAdd).toHaveBeenCalledWith(
      { role: "underwriter", email: "uw@lender.example" },
      expect.anything(),
    );
  });
});

describe("a party we can reach", () => {
  it("shows who, and offers to prepare a request rather than to send one", () => {
    loaded([REACHABLE]);
    render(<PartyRequestsPanel fileId="f1" />, { wrapper });

    expect(screen.getByText(/Books LLP · books@cpa.example/)).toBeDefined();
    expect(screen.getByRole("button", { name: "Build request" })).toBeDefined();
    // The word that would be a lie. The draft still goes through the send gate.
    expect(screen.queryByRole("button", { name: /^Send/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Save address" })).toBeNull();
  });

  it("builds for the party the row is about", () => {
    loaded([REACHABLE, UNREACHABLE]);
    render(<PartyRequestsPanel fileId="f1" />, { wrapper });

    fireEvent.click(screen.getByRole("button", { name: "Build request" }));

    expect(mockBuild).toHaveBeenCalledWith("cpa", expect.anything());
  });
});

describe("the panel", () => {
  it("leaves the borrower to its own panel", () => {
    // Two places to press send from, and the accumulating request is the one carrying the
    // borrower's retrieval guidance.
    loaded([
      { ...REACHABLE, party: "borrower", role: "borrower", needs: [{ id: "b", title: "W-2" }] },
      REACHABLE,
    ]);
    render(<PartyRequestsPanel fileId="f1" />, { wrapper });

    expect(screen.queryByText("Borrower")).toBeNull();
    expect(screen.getAllByRole("listitem").filter((li) => li.querySelector("button"))).toHaveLength(
      1,
    );
  });

  it("calls an empty list correct rather than incomplete", () => {
    loaded([]);
    render(<PartyRequestsPanel fileId="f1" />, { wrapper });

    expect(screen.getByText("Nothing is needed from anyone else")).toBeDefined();
    expect(screen.queryByRole("button")).toBeNull();
  });
});
