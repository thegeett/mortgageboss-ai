// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const post = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/client", () => ({ apiClient: { post } }));

import type { Invite, InviteIssued } from "@/lib/types/invites";
import { CopyLinkCard, InvitationsPanel, linkState } from "./invitations-panel";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const NOW = new Date("2026-11-13T12:00:00Z").getTime();
const OPEN: Invite = {
  id: "i-open",
  email: "sam@x.com",
  roles: ["processor"],
  invited_by_name: "Priya Desai",
  created_at: "2026-11-13T10:00:00Z",
  last_sent_at: "2026-11-13T10:00:00Z",
  expires_at: "2026-11-20T10:00:00Z",
  send_count: 1,
  expired: false,
};
const EXPIRED: Invite = {
  ...OPEN,
  id: "i-old",
  email: "lena@x.com",
  roles: ["admin", "processor"],
  expires_at: "2026-11-09T10:00:00Z",
  expired: true,
};

function renderPanel(onIssued = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <InvitationsPanel invites={[OPEN, EXPIRED]} onIssued={onIssued} />
    </QueryClientProvider>,
  );
  return { onIssued };
}

describe("linkState", () => {
  it("says how long a link has left, or when it expired", () => {
    expect(linkState(OPEN, NOW)).toBe("Expires in 7 days");
    expect(linkState(EXPIRED, NOW)).toBe("Expired Nov 9");
    expect(linkState({ ...OPEN, expires_at: "2026-11-13T20:00:00Z" }, NOW)).toBe("Expires today");
  });
});

describe("InvitationsPanel", () => {
  it("lists each invitation with its roles, inviter and link state", () => {
    renderPanel();
    const lena = screen.getByText("lena@x.com").closest("tr");
    expect(lena && within(lena).getByText("Admin")).toBeTruthy();
    expect(lena && within(lena).getByText(/^Expired /)).toBeTruthy();
    expect(screen.getAllByText(/Priya Desai,/)).toHaveLength(2);
  });

  it("Resend asks the server for a new link and passes it on", async () => {
    const issued = { invite: OPEN, accept_url: "http://localhost:3000/accept-invite#t" };
    post.mockResolvedValue({ data: issued });
    const { onIssued } = renderPanel();

    const row = screen.getByText("sam@x.com").closest("tr") as HTMLElement;
    fireEvent.click(within(row).getByRole("button", { name: "Resend" }));

    await waitFor(() => expect(onIssued).toHaveBeenCalledWith(issued, "resent"));
    expect(post).toHaveBeenCalledWith("/api/v1/invites/i-open/resend");
  });

  it("Cancel revokes the invitation", async () => {
    post.mockResolvedValue({ data: EXPIRED });
    renderPanel();

    const row = screen.getByText("lena@x.com").closest("tr") as HTMLElement;
    fireEvent.click(within(row).getByRole("button", { name: "Cancel" }));

    await waitFor(() => expect(post).toHaveBeenCalledWith("/api/v1/invites/i-old/revoke"));
  });

  it("shows the throttle's sentence when a resend comes too soon", async () => {
    post.mockRejectedValue({
      isAxiosError: true,
      response: {
        status: 429,
        data: { error: { type: "rate_limited", message: "Try again in a minute" } },
      },
    });
    renderPanel();

    const row = screen.getByText("sam@x.com").closest("tr") as HTMLElement;
    fireEvent.click(within(row).getByRole("button", { name: "Resend" }));

    expect((await screen.findByRole("alert")).textContent).toBe("Try again in a minute");
  });
});

describe("CopyLinkCard", () => {
  const issued = (accept_url: string | null): InviteIssued => ({ invite: OPEN, accept_url });

  it("shows the link once, with Copy and Dismiss, when the server sent one", () => {
    const onDismiss = vi.fn();
    render(
      <CopyLinkCard
        issued={issued("http://localhost:3000/accept-invite#tok")}
        verb="created"
        onDismiss={onDismiss}
      />,
    );
    expect(screen.getByText("Invitation created for sam@x.com.")).toBeTruthy();
    expect((screen.getByLabelText("Invitation link") as HTMLInputElement).value).toBe(
      "http://localhost:3000/accept-invite#tok",
    );
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(onDismiss).toHaveBeenCalled();
  });

  it("renders nothing when the link went by email", () => {
    const { container } = render(
      <CopyLinkCard issued={issued(null)} verb="created" onDismiss={vi.fn()} />,
    );
    expect(container.innerHTML).toBe("");
  });
});
