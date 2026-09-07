// @vitest-environment jsdom
/**
 * LP-808 — the connection screen, and the four states it must tell apart.
 *
 * THE STALENESS SENTENCE IS THE REASON THIS SCREEN EXISTS. §3: "the worst failure here is silent —
 * the rule was removed, nothing errored, and documents stopped arriving." A screen that says
 * "connected" to all four states is exactly as useful as no screen.
 *
 *   revoked                  we turned it off
 *   not verified             the rule has not been made yet — nothing is wrong
 *   awaiting first message   the rule may exist; nothing has arrived to prove it
 *   verified but stale       it worked and then stopped, which is the silent failure
 *
 * "Not set up yet" and "no mail for six days" send an admin to two different places, and merging
 * them sends them to the wrong one.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

const mockConnections = vi.fn();
const mockConnect = vi.fn();
const mockRevoke = vi.fn();

vi.mock("@/lib/api/mailbox-connections", () => ({
  useMailboxConnections: () => mockConnections(),
  useConnectionSteps: () => ({ data: { provider: "google", steps: ["one"] }, isPending: false }),
  useConnectMailbox: () => ({ mutate: mockConnect, isPending: false }),
  useEmailSteps: () => ({ mutate: vi.fn(), isPending: false }),
  useRevokeConnection: () => ({ mutate: mockRevoke, isPending: false }),
}));
vi.mock("@/lib/toast", () => ({ notifySuccess: vi.fn(), notifyError: vi.fn() }));

import { MailboxConnections, connectionState } from "./mailbox-connections";

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const BASE = {
  id: "c1",
  kind: "forwarded_alias",
  provider: "google",
  address: "co-abc123@inbox.example.com",
  source_address: "docs@herco.example",
  status: "connected" as const,
  verification: "verified" as const,
  last_success_at: new Date(Date.now() - 3600 * 1000).toISOString(),
  consecutive_failures: 0,
  is_stale: false,
  stale_after_days: 4,
};

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("the state sentence", () => {
  it("distinguishes all four, and none of them is just 'connected'", () => {
    const sentences = [
      connectionState({ ...BASE, status: "revoked" }),
      connectionState({ ...BASE, verification: "not_verified" }),
      connectionState({ ...BASE, verification: "awaiting_first_message" }),
      connectionState({ ...BASE, is_stale: true }),
      connectionState(BASE),
    ];

    expect(new Set(sentences).size).toBe(5);
  });

  it("says a connection that never worked is not set up — not that mail stopped", () => {
    // Telling somebody whose admin has not made the rule that "no mail has arrived in 4 days"
    // describes a failure that has not happened and hides the one that has.
    const sentence = connectionState({
      ...BASE,
      verification: "not_verified",
      last_success_at: null,
    });

    expect(sentence).toMatch(/Not set up yet/);
    expect(sentence).not.toMatch(/No mail received/);
  });

  it("names how long it has been quiet when a working connection goes stale", () => {
    const sentence = connectionState({
      ...BASE,
      is_stale: true,
      last_success_at: new Date(Date.now() - 6 * 24 * 3600 * 1000).toISOString(),
    });

    expect(sentence).toMatch(/No mail received since/);
    expect(sentence).toMatch(/check the routing rule/);
  });

  it("reads staleness off the server rather than recomputing it", () => {
    // The server holds the threshold. Recombining `last_success_at` and a local constant here is a
    // second answer to the same question, and the two eventually disagree.
    const old = new Date(Date.now() - 30 * 24 * 3600 * 1000).toISOString();

    expect(connectionState({ ...BASE, last_success_at: old, is_stale: false })).toMatch(/Working/);
  });
});

describe("the list", () => {
  it("shows the address and warns when it is stale", () => {
    mockConnections.mockReturnValue({
      data: [{ ...BASE, is_stale: true }],
      isPending: false,
      isError: false,
    });

    render(<MailboxConnections />, { wrapper });

    expect(screen.getByText("co-abc123@inbox.example.com")).toBeDefined();
    expect(screen.getByText(/No mail received since/)).toBeDefined();
  });

  it("offers Revoke only while the address still accepts mail", () => {
    mockConnections.mockReturnValue({
      data: [BASE, { ...BASE, id: "c2", status: "revoked" as const }],
      isPending: false,
      isError: false,
    });

    render(<MailboxConnections />, { wrapper });

    expect(screen.getAllByRole("button", { name: "Revoke" })).toHaveLength(1);
  });

  it("says file addresses still work when nothing is connected", () => {
    // A processor reading "no mailbox is connected" could reasonably conclude no mail arrives at
    // all. Route A is unaffected and the empty state says so.
    mockConnections.mockReturnValue({ data: [], isPending: false, isError: false });

    render(<MailboxConnections />, { wrapper });

    expect(screen.getByText(/file's own address still arrives/)).toBeDefined();
  });
});

describe("creating one", () => {
  it("sends null rather than an empty alias", () => {
    mockConnections.mockReturnValue({ data: [], isPending: false, isError: false });
    render(<MailboxConnections />, { wrapper });

    screen.getByRole("button", { name: "Create address" }).click();

    expect(mockConnect).toHaveBeenCalledWith(
      { provider: "google", source_address: null },
      expect.anything(),
    );
  });
});
