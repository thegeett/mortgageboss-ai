// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

const get = vi.hoisted(() => vi.fn());
const patch = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/client", () => ({ apiClient: { get, patch } }));
const fetchCurrentUser = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/auth", () => ({ fetchCurrentUser }));

import { useAuthStore } from "@/lib/stores/auth-store";

import { CompanySettingsCard } from "./company-settings-card";

const DEFAULTS = {
  processors_can_create_loans: true,
  processors_can_invite_borrowers: true,
  restrict_loans_to_team: false,
};

function forbidden() {
  return {
    isAxiosError: true,
    response: {
      status: 403,
      data: { error: { type: "forbidden", message: "Insufficient permissions" } },
    },
  };
}

function renderCard(ui: React.ReactElement = <CompanySettingsCard />) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

afterEach(() => {
  cleanup();
  get.mockReset();
  patch.mockReset();
  fetchCurrentUser.mockReset();
  useAuthStore.setState({ user: null });
});

describe("CompanySettingsCard", () => {
  it("never shows an error while loading successfully (review finding 2)", async () => {
    // The flash lasted one render, gone before any `findBy` could see it, so watch the DOM.
    const alerts: string[] = [];
    const observer = new MutationObserver(() => {
      for (const node of document.querySelectorAll('[role="alert"]')) {
        alerts.push(node.textContent ?? "");
      }
    });
    observer.observe(document.body, { childList: true, subtree: true });
    get.mockResolvedValueOnce({ data: DEFAULTS });
    renderCard();

    await screen.findByRole("checkbox", { name: /Processors may create loan files/ });
    observer.disconnect();

    expect(alerts).toEqual([]);
  });

  it("re-reads the signed-in user after a save, so their permissions follow the setting", async () => {
    get.mockResolvedValueOnce({ data: DEFAULTS });
    patch.mockResolvedValueOnce({ data: { ...DEFAULTS, processors_can_create_loans: false } });
    const refreshed = {
      id: "u1",
      email: "a@acme.com",
      first_name: "A",
      last_name: "D",
      roles: ["admin", "processor"],
      permissions: ["company.settings.manage"],
      is_owner: true,
      company_id: "c1",
    };
    fetchCurrentUser.mockResolvedValueOnce(refreshed);
    renderCard();

    fireEvent.click(
      await screen.findByRole("checkbox", { name: /Processors may create loan files/ }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Save settings" }));

    await waitFor(() => expect(useAuthStore.getState().user).toEqual(refreshed));
  });

  it("loads the three settings into checkboxes", async () => {
    get.mockResolvedValueOnce({ data: DEFAULTS });
    renderCard();

    const create = await screen.findByRole("checkbox", {
      name: /Processors may create loan files/,
    });
    expect((create as HTMLInputElement).checked).toBe(true);
    expect(
      (screen.getByRole("checkbox", { name: /Restrict loan files/ }) as HTMLInputElement).checked,
    ).toBe(false);
    expect(get).toHaveBeenCalledWith("/api/v1/company/settings");
    // Nothing changed yet, so there is nothing to save.
    expect(
      (screen.getByRole("button", { name: "Save settings" }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });

  it("saves a change and shows the saved state", async () => {
    get.mockResolvedValueOnce({ data: DEFAULTS });
    patch.mockResolvedValueOnce({ data: { ...DEFAULTS, processors_can_create_loans: false } });
    renderCard();

    fireEvent.click(
      await screen.findByRole("checkbox", { name: /Processors may create loan files/ }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Save settings" }));

    await screen.findByText("Saved.");
    expect(patch).toHaveBeenCalledWith("/api/v1/company/settings", {
      ...DEFAULTS,
      processors_can_create_loans: false,
    });
  });

  it("shows the server's 403 to a user who may not manage settings", async () => {
    get.mockRejectedValueOnce(forbidden());
    renderCard();

    expect(await screen.findByRole("alert")).toHaveProperty(
      "textContent",
      "Insufficient permissions",
    );
    expect(screen.queryByRole("checkbox")).toBeNull();
  });

  it("shows a 403 on save too", async () => {
    get.mockResolvedValueOnce({ data: DEFAULTS });
    patch.mockRejectedValueOnce(forbidden());
    renderCard();

    fireEvent.click(await screen.findByRole("checkbox", { name: /Restrict loan files/ }));
    fireEvent.click(screen.getByRole("button", { name: "Save settings" }));

    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toBe("Insufficient permissions"),
    );
  });
});
