// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn(), post: vi.fn(), delete: vi.fn() }));
vi.mock("@/lib/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/client")>()),
  apiClient: api,
}));
const router = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => router }));

import { useAuthStore } from "@/lib/stores/auth-store";
import { TeamCard } from "./team-card";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.restoreAllMocks();
  useAuthStore.setState({ user: null });
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
  me,
}: {
  team: Record<string, unknown>;
  officers?: unknown[];
  processors?: unknown[];
  /** What `/auth/me` answers now; left out, the request fails. */
  me?: Record<string, unknown>;
}) {
  api.get.mockImplementation(async (url: string, config?: { params?: { team_role?: string } }) => {
    if (url.endsWith("/team")) return { data: team };
    if (url === "/api/v1/auth/me" && me) return { data: me };
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

  describe("a restricted loan officer handing their own file away (LP-MB-Admin-06)", () => {
    function user(id: string, restricted: boolean) {
      return {
        id,
        email: "daniel@x.com",
        first_name: "Daniel",
        last_name: "Okafor",
        roles: ["loan_officer"],
        permissions: ["loan.create", "loan.team.change"],
        is_owner: false,
        restricted,
        company_id: "c-1",
      };
    }

    function signIn({ id, restricted }: { id: string; restricted: boolean }) {
      useAuthStore.setState({ user: user(id, restricted) });
    }

    async function pick(value: string) {
      fireEvent.click(await screen.findByRole("button", { name: "Change" }));
      fireEvent.change(await screen.findByLabelText("Choose the loan officer"), {
        target: { value },
      });
    }

    const AFTER = { loan_officer: null, processors: [], can_change: false };

    it("asks first, and goes to the pipeline after the change", async () => {
      signIn({ id: "u-daniel", restricted: true });
      serve({ team: { loan_officer: DANIEL, processors: [], can_change: true } });
      api.put.mockResolvedValue({ data: AFTER });
      const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
      renderCard();

      await pick("u-lena");

      await waitFor(() =>
        expect(confirm).toHaveBeenCalledWith("You will no longer see this file."),
      );
      await waitFor(() =>
        expect(api.put).toHaveBeenCalledWith("/api/v1/loan-files/LF-1/team/loan-officer", {
          user_id: "u-lena",
        }),
      );
      await waitFor(() => expect(router.push).toHaveBeenCalledWith("/dashboard"));
    });

    it("asks when clearing the slot too", async () => {
      signIn({ id: "u-daniel", restricted: true });
      serve({ team: { loan_officer: DANIEL, processors: [], can_change: true } });
      api.put.mockResolvedValue({ data: AFTER });
      const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
      renderCard();

      await pick("__none__");

      await waitFor(() =>
        expect(confirm).toHaveBeenCalledWith("You will no longer see this file."),
      );
      await waitFor(() =>
        expect(api.put).toHaveBeenCalledWith("/api/v1/loan-files/LF-1/team/loan-officer", {
          user_id: null,
        }),
      );
      await waitFor(() => expect(router.push).toHaveBeenCalledWith("/dashboard"));
    });

    it("changes nothing when they say no", async () => {
      signIn({ id: "u-daniel", restricted: true });
      serve({ team: { loan_officer: DANIEL, processors: [], can_change: true } });
      const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
      renderCard();

      await pick("u-lena");

      // Asked first, so the "no PUT" below is about the answer, not about not having asked yet.
      await waitFor(() => expect(confirm).toHaveBeenCalled());
      expect(api.put).not.toHaveBeenCalled();
      expect(router.push).not.toHaveBeenCalled();
    });

    it("asks the server, so a setting turned on since sign-in counts (review finding 4)", async () => {
      signIn({ id: "u-daniel", restricted: false });
      serve({
        team: { loan_officer: DANIEL, processors: [], can_change: true },
        me: user("u-daniel", true),
      });
      api.put.mockResolvedValue({ data: AFTER });
      const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
      renderCard();

      await pick("u-lena");

      await waitFor(() =>
        expect(confirm).toHaveBeenCalledWith("You will no longer see this file."),
      );
      await waitFor(() => expect(router.push).toHaveBeenCalledWith("/dashboard"));
      expect(useAuthStore.getState().user?.restricted).toBe(true);
    });

    it("falls back to the stored flag when the server cannot answer", async () => {
      signIn({ id: "u-daniel", restricted: true });
      serve({ team: { loan_officer: DANIEL, processors: [], can_change: true } });
      api.put.mockResolvedValue({ data: AFTER });
      const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
      renderCard();

      await pick("u-lena");

      await waitFor(() =>
        expect(confirm).toHaveBeenCalledWith("You will no longer see this file."),
      );
    });

    it("does not ask a loan officer who will still see it (the setting off)", async () => {
      signIn({ id: "u-daniel", restricted: false });
      serve({
        team: { loan_officer: DANIEL, processors: [], can_change: true },
        me: user("u-daniel", false),
      });
      api.put.mockResolvedValue({ data: AFTER });
      const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
      renderCard();

      await pick("u-lena");

      await waitFor(() => expect(api.put).toHaveBeenCalled());
      expect(confirm).not.toHaveBeenCalled();
      expect(router.push).not.toHaveBeenCalled();
    });

    it("does not ask someone who is not the file's loan officer", async () => {
      signIn({ id: "u-someone", restricted: true });
      serve({ team: { loan_officer: DANIEL, processors: [], can_change: true } });
      api.put.mockResolvedValue({ data: AFTER });
      const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
      renderCard();

      await pick("u-lena");

      await waitFor(() => expect(api.put).toHaveBeenCalled());
      expect(confirm).not.toHaveBeenCalled();
      expect(router.push).not.toHaveBeenCalled();
    });
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
