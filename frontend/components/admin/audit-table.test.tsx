// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const get = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/client", () => ({ apiClient: { get } }));

import type { AuditEntry } from "@/lib/types/users";
import { AuditTable } from "./audit-table";
import { ELENA } from "./test-people";

afterEach(() => {
  cleanup();
  get.mockReset();
});

function entry(id: string, overrides: Partial<AuditEntry> = {}): AuditEntry {
  return {
    id,
    created_at: "2026-11-09T16:40:00Z",
    actor: { id: "p-me", name: "Marcus Hill" },
    action: "user_roles_changed",
    target_type: "user",
    target_id: ELENA.id,
    target_name: "Elena Ruiz",
    summary: "Changed Elena Ruiz's roles",
    detail: {
      changes: [{ field: "roles", from: ["processor"], to: ["loan_officer", "processor"] }],
    },
    ...overrides,
  };
}

function renderTable() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <AuditTable people={[ELENA]} />
    </QueryClientProvider>,
  );
}

describe("AuditTable", () => {
  it("renders who, what and the change as from → to", async () => {
    get.mockResolvedValueOnce({ data: { items: [entry("a")], next_cursor: null, total: 1 } });
    renderTable();

    expect(await screen.findByText("Changed Elena Ruiz's roles")).toBeTruthy();
    expect(screen.getByText("Marcus Hill")).toBeTruthy();
    const change = screen.getByText("loan_officer, processor").closest("li");
    expect(change?.textContent).toBe("processor → loan_officer, processor");
    expect(screen.getByText("1 of 1")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Load more" })).toBeNull();
  });

  it("shows the system for a row with no actor, and on/off for a flag", async () => {
    get.mockResolvedValueOnce({
      data: {
        items: [
          entry("s", {
            actor: null,
            summary: "Company settings changed",
            detail: { changes: [{ field: "restrict_loans_to_team", from: false, to: true }] },
          }),
        ],
        next_cursor: null,
        total: 1,
      },
    });
    renderTable();
    expect(await screen.findByText("System")).toBeTruthy();
    expect(screen.getByText("on").closest("li")?.textContent).toBe("off → on");
  });

  it("loads the next page through the cursor", async () => {
    get
      .mockResolvedValueOnce({ data: { items: [entry("a")], next_cursor: "c1", total: 2 } })
      .mockResolvedValueOnce({
        data: {
          items: [entry("b", { summary: "Deactivated Elena Ruiz" })],
          next_cursor: null,
          total: 2,
        },
      });
    renderTable();

    fireEvent.click(await screen.findByRole("button", { name: "Load more" }));

    expect(await screen.findByText("Deactivated Elena Ruiz")).toBeTruthy();
    expect(screen.getByText("2 of 2")).toBeTruthy();
    expect(get.mock.calls[1]?.[1]).toMatchObject({ params: { before: "c1" } });
  });

  it("asks the server again when a filter changes", async () => {
    get.mockResolvedValue({ data: { items: [], next_cursor: null, total: 0 } });
    renderTable();
    await screen.findByText("Nothing recorded for these filters.");

    fireEvent.change(screen.getByLabelText("Who"), { target: { value: ELENA.id } });

    await waitFor(() =>
      expect(get.mock.calls.at(-1)?.[1]).toMatchObject({ params: { actor_user_id: ELENA.id } }),
    );
  });
});
