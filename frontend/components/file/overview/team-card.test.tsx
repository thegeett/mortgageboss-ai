// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn(), post: vi.fn(), delete: vi.fn() }));
vi.mock("@/lib/api/client", () => ({ apiClient: api }));

import { TeamCard } from "./team-card";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const ELENA = {
  id: "m-elena",
  user_id: "u-elena",
  name: "Elena Ruiz",
  email: "elena@x.com",
  team_role: "processor",
  nmls_id: null,
  licensed_states: [],
};
const DANIEL = {
  id: "m-daniel",
  user_id: "u-daniel",
  name: "Daniel Okafor",
  email: "daniel@x.com",
  team_role: "loan_officer",
  nmls_id: "123456",
  licensed_states: ["NJ", "NY"],
};
const TOM = { id: "u-tom", name: "Tom Becker", roles: ["processor"], file_count: 14 };
const LENA = { id: "u-lena", name: "Lena Park", roles: ["loan_officer"], file_count: 2 };

function serve({
  team,
  officers = [LENA],
  processors = [TOM],
}: {
  team: Record<string, unknown>;
  officers?: unknown[];
  processors?: unknown[];
}) {
  api.get.mockImplementation(async (url: string, config?: { params?: { team_role?: string } }) => {
    if (url.endsWith("/team")) return { data: team };
    if (url === "/api/v1/users/assignable") {
      return { data: config?.params?.team_role === "loan_officer" ? officers : processors };
    }
    throw new Error(`unexpected ${url}`);
  });
}

function renderCard() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <TeamCard fileId="LF-1" />
    </QueryClientProvider>,
  );
}

describe("TeamCard", () => {
  it("is read-only for someone who may not change the team", async () => {
    serve({ team: { loan_officer: DANIEL, processors: [ELENA], can_change: false } });
    renderCard();

    expect(await screen.findByText("Elena Ruiz")).toBeTruthy();
    expect(screen.getByText(/NMLS 123456 · NJ, NY/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Change" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Remove/ })).toBeNull();
    expect(screen.queryByLabelText("Add processor")).toBeNull();
  });

  it("hides the loan officer slot in a company with no loan officers", async () => {
    serve({ team: { loan_officer: null, processors: [ELENA], can_change: true }, officers: [] });
    renderCard();

    expect(await screen.findByText("Elena Ruiz")).toBeTruthy();
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(3));
    expect(screen.queryByRole("region", { name: "Loan officer" })).toBeNull();
    expect(screen.queryByText("No loan officer")).toBeNull();
  });

  it("lets an admin change the loan officer", async () => {
    serve({ team: { loan_officer: DANIEL, processors: [], can_change: true } });
    api.put.mockResolvedValue({
      data: {
        loan_officer: { ...DANIEL, id: "m-lena", user_id: "u-lena", name: "Lena Park" },
        processors: [],
        can_change: true,
      },
    });
    renderCard();

    fireEvent.click(await screen.findByRole("button", { name: "Change" }));
    fireEvent.change(await screen.findByLabelText("Choose the loan officer"), {
      target: { value: "u-lena" },
    });

    await waitFor(() =>
      expect(api.put).toHaveBeenCalledWith("/api/v1/loan-files/LF-1/team/loan-officer", {
        user_id: "u-lena",
      }),
    );
    expect(await screen.findByText("Lena Park")).toBeTruthy();
  });

  it("adds a processor (showing each person's load) and removes one", async () => {
    serve({ team: { loan_officer: null, processors: [ELENA], can_change: true } });
    api.post.mockResolvedValue({
      data: {
        loan_officer: null,
        processors: [ELENA, { ...ELENA, id: "m-tom", user_id: "u-tom", name: "Tom Becker" }],
        can_change: true,
      },
    });
    api.delete.mockResolvedValue({
      data: { loan_officer: null, processors: [], can_change: true },
    });
    renderCard();

    const picker = await screen.findByLabelText("Add processor");
    await waitFor(() => expect(within(picker).getByText("Tom Becker · 14 files")).toBeTruthy());
    fireEvent.change(picker, { target: { value: "u-tom" } });
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith("/api/v1/loan-files/LF-1/team/members", {
        user_id: "u-tom",
      }),
    );
    fireEvent.click(await screen.findByRole("button", { name: "Remove Elena Ruiz" }));
    await waitFor(() =>
      expect(api.delete).toHaveBeenCalledWith("/api/v1/loan-files/LF-1/team/members/m-elena"),
    );
  });

  it("shows the server's refusal", async () => {
    serve({ team: { loan_officer: null, processors: [], can_change: true } });
    api.post.mockRejectedValue({
      isAxiosError: true,
      response: {
        status: 422,
        data: {
          error: {
            type: "validation_error",
            message: "Tom Becker needs the Processor role to be a processor",
          },
        },
      },
    });
    renderCard();

    const picker = await screen.findByLabelText("Add processor");
    await waitFor(() => expect(within(picker).getByText("Tom Becker · 14 files")).toBeTruthy());
    fireEvent.change(picker, { target: { value: "u-tom" } });

    expect((await screen.findByRole("alert")).textContent).toBe(
      "Tom Becker needs the Processor role to be a processor",
    );
  });
});
