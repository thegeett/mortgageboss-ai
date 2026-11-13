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
        : url === "/api/v1/invites"
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
