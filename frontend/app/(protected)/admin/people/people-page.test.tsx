// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("@/lib/api/client", () => ({ apiClient: api }));

import { ELENA, EMPTY_PAGE, ME, OWNER } from "@/components/admin/test-people";
import { useAuthStore } from "@/lib/stores/auth-store";
import PeoplePage from "./page";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("People page", () => {
  it("deactivates a person after the dialog confirms, and their row goes inactive", async () => {
    useAuthStore.setState({ user: { id: ME.id } as never, accessToken: "t" });
    api.get.mockImplementation(async (url: string) =>
      url === "/api/v1/users"
        ? { data: [OWNER, ME, ELENA] }
        : url === "/api/v1/invites" || url === "/api/v1/users/assignable"
          ? { data: [] }
          : { data: EMPTY_PAGE },
    );
    api.post.mockResolvedValue({ data: { ...ELENA, is_active: false } });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <PeoplePage />
      </QueryClientProvider>,
    );

    fireEvent.click(await screen.findByText("Elena Ruiz"));
    fireEvent.click(screen.getByRole("button", { name: "Deactivate" }));
    const dialog = await screen.findByRole("dialog", { name: "Deactivate Elena Ruiz?" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Deactivate" }));

    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(`/api/v1/users/${ELENA.id}/deactivate`),
    );
    // The open sheet now offers Reactivate, read from the same list the table shows.
    expect(await screen.findByRole("button", { name: "Reactivate" })).toBeTruthy();
    fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
    fireEvent.click(await screen.findByLabelText("Show inactive"));
    const row = screen.getByText("Elena Ruiz").closest("tr");
    expect(row && within(row).getByText("Inactive")).toBeTruthy();
  });
});

describe("People page — the copy-link card (LP-MB-Admin-04 review, finding 10)", () => {
  it("shows a newly resent link as not yet copied", async () => {
    Object.assign(navigator, { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } });
    useAuthStore.setState({ user: { id: ME.id } as never, accessToken: "t" });
    const invite = {
      id: "i1",
      email: "sam@x.com",
      roles: ["processor"],
      invited_by_name: "Marcus Hill",
      created_at: "2026-11-13T10:00:00Z",
      last_sent_at: "2026-11-13T10:00:00Z",
      expires_at: "2099-11-20T10:00:00Z",
      send_count: 1,
      expired: false,
    };
    api.get.mockImplementation(async (url: string) =>
      url === "/api/v1/invites" ? { data: [invite] } : { data: [OWNER, ME, ELENA] },
    );
    api.post
      .mockResolvedValueOnce({ data: { invite, accept_url: "http://l/accept-invite#first" } })
      .mockResolvedValueOnce({ data: { invite, accept_url: "http://l/accept-invite#second" } });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <PeoplePage />
      </QueryClientProvider>,
    );

    fireEvent.click(await screen.findByRole("tab", { name: /Invitations/ }));
    const row = (await screen.findByText("sam@x.com")).closest("tr") as HTMLElement;
    fireEvent.click(within(row).getByRole("button", { name: "Resend" }));
    fireEvent.click(await screen.findByRole("button", { name: "Copy link" }));
    expect(await screen.findByRole("button", { name: "Copied" })).toBeTruthy();

    fireEvent.click(within(row).getByRole("button", { name: "Resend" }));

    await waitFor(() =>
      expect((screen.getByLabelText("Invitation link") as HTMLInputElement).value).toBe(
        "http://l/accept-invite#second",
      ),
    );
    expect(screen.getByRole("button", { name: "Copy link" })).toBeTruthy();
  });
});
