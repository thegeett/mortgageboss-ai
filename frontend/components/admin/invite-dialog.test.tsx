// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const post = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/client", () => ({ apiClient: { post } }));

import { InviteDialog } from "./invite-dialog";
import { refusal } from "./test-people";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function renderDialog() {
  const onIssued = vi.fn();
  const onOpenChange = vi.fn();
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <InviteDialog open onOpenChange={onOpenChange} onIssued={onIssued} />
    </QueryClientProvider>,
  );
  return { onIssued, onOpenChange };
}

describe("InviteDialog", () => {
  it("starts with Processor ticked and sends the email and the chosen roles", async () => {
    const issued = { invite: { id: "i1", email: "sam@x.com" }, accept_url: null };
    post.mockResolvedValue({ data: issued });
    const { onIssued, onOpenChange } = renderDialog();

    expect((screen.getByRole("checkbox", { name: /Processor/ }) as HTMLInputElement).checked).toBe(
      true,
    );
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: " sam@x.com " } });
    fireEvent.click(screen.getByRole("checkbox", { name: /^Admin/ }));
    fireEvent.click(screen.getByRole("button", { name: "Send invitation" }));

    await waitFor(() => expect(onIssued).toHaveBeenCalledWith(issued));
    expect(post).toHaveBeenCalledWith("/api/v1/invites", {
      email: "sam@x.com",
      roles: ["processor", "admin"],
    });
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("shows the server's refusal under the email field and stays open", async () => {
    post.mockRejectedValue(refusal(409, "Already on your team"));
    const { onOpenChange } = renderDialog();

    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "here@x.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Send invitation" }));

    expect((await screen.findByRole("alert")).textContent).toBe("Already on your team");
    expect(screen.getByLabelText("Email").getAttribute("aria-describedby")).toBe(
      "invite-email-error",
    );
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
  });

  it("does not offer the owner as a role", () => {
    renderDialog();
    expect(screen.queryByText(/Owner/)).toBeNull();
    expect(screen.getAllByRole("checkbox")).toHaveLength(3);
  });
});
