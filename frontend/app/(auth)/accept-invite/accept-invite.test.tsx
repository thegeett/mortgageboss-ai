// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const post = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/client", () => ({ apiClient: { post } }));
const replace = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));

import { useAuthStore } from "@/lib/stores/auth-store";
import AcceptInvitePage from "./page";

const TOKEN = "abc_DEF-123";
const LOOKUP = {
  company_name: "Summit Mortgage Processing",
  email: "sam@summit.com",
  roles: ["processor"],
  invited_by_name: "Priya Desai",
};
const INVALID = {
  isAxiosError: true,
  response: {
    status: 404,
    data: { error: { type: "not_found", message: "This invitation is no longer valid" } },
  },
};

beforeEach(() => {
  window.history.replaceState(null, "", `/accept-invite#${TOKEN}`);
  useAuthStore.setState({ user: null, accessToken: null });
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("Accept invite page", () => {
  it("reads the token from the fragment, sends it in the body, and clears it from the URL", async () => {
    post.mockResolvedValueOnce({ data: LOOKUP });
    render(<AcceptInvitePage />);

    expect(await screen.findByText("Join Summit Mortgage Processing")).toBeTruthy();
    expect(post).toHaveBeenCalledWith("/api/v1/invites/lookup", { token: TOKEN });
    // Never in the path or query, and no longer in the address bar.
    expect(window.location.href).not.toContain(TOKEN);
    expect(screen.getByText(/Priya Desai invited you as/)).toBeTruthy();
    expect((screen.getByLabelText("Email") as HTMLInputElement).value).toBe("sam@summit.com");
  });

  it("creates the account, stores the session and goes to the dashboard", async () => {
    const user = { id: "u1", email: "sam@summit.com", permissions: ["loan.create"] };
    post
      .mockResolvedValueOnce({ data: LOOKUP })
      .mockResolvedValueOnce({ data: { access_token: "access", token_type: "bearer", user } });
    render(<AcceptInvitePage />);
    await screen.findByText("Join Summit Mortgage Processing");

    fireEvent.change(screen.getByLabelText("First name"), { target: { value: "Sam" } });
    fireEvent.change(screen.getByLabelText("Last name"), { target: { value: "Whitfield" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "long enough pw" } });
    fireEvent.click(screen.getByRole("button", { name: "Create account and sign in" }));

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/dashboard"));
    expect(post).toHaveBeenLastCalledWith("/api/v1/invites/accept", {
      token: TOKEN,
      first_name: "Sam",
      last_name: "Whitfield",
      password: "long enough pw", // pragma: allowlist secret  (a test value)
    });
    expect(useAuthStore.getState().accessToken).toBe("access");
  });

  it("shows the server's password rule on a 422", async () => {
    post.mockResolvedValueOnce({ data: LOOKUP }).mockRejectedValueOnce({
      isAxiosError: true,
      response: {
        status: 422,
        data: {
          error: { type: "validation_error", message: "Password must be at least 8 characters." },
        },
      },
    });
    render(<AcceptInvitePage />);
    await screen.findByText("Join Summit Mortgage Processing");

    fireEvent.change(screen.getByLabelText("First name"), { target: { value: "Sam" } });
    fireEvent.change(screen.getByLabelText("Last name"), { target: { value: "W" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "short" } });
    fireEvent.click(screen.getByRole("button", { name: "Create account and sign in" }));

    expect((await screen.findByRole("alert")).textContent).toBe(
      "Password must be at least 8 characters.",
    );
  });

  it("shows the single invalid-link card when the lookup fails", async () => {
    post.mockRejectedValueOnce(INVALID);
    render(<AcceptInvitePage />);

    expect(await screen.findByText("This invitation is no longer valid")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Go to sign in" }).getAttribute("href")).toBe("/login");
  });

  it("shows the same card with no token at all, without asking the server", async () => {
    window.history.replaceState(null, "", "/accept-invite");
    render(<AcceptInvitePage />);

    expect(await screen.findByText("This invitation is no longer valid")).toBeTruthy();
    expect(post).not.toHaveBeenCalled();
  });

  it("turns a 404 on accept (used meanwhile) into the same card", async () => {
    post.mockResolvedValueOnce({ data: LOOKUP }).mockRejectedValueOnce(INVALID);
    render(<AcceptInvitePage />);
    await screen.findByText("Join Summit Mortgage Processing");

    fireEvent.change(screen.getByLabelText("First name"), { target: { value: "Sam" } });
    fireEvent.change(screen.getByLabelText("Last name"), { target: { value: "W" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "long enough pw" } });
    fireEvent.click(screen.getByRole("button", { name: "Create account and sign in" }));

    expect(await screen.findByText("This invitation is no longer valid")).toBeTruthy();
  });
});
