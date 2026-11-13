// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ get: vi.fn(), patch: vi.fn(), put: vi.fn(), post: vi.fn() }));
vi.mock("@/lib/api/client", () => ({ apiClient: api }));

import type { Person } from "@/lib/types/users";
import { PersonSheet } from "./person-sheet";
import { ELENA, EMPTY_PAGE, ME, OWNER, person, refusal } from "./test-people";

beforeEach(() => {
  api.get.mockResolvedValue({ data: EMPTY_PAGE });
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function renderSheet(who: Person, onClose = vi.fn()) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <PersonSheet person={who} currentUserId={ME.id} onClose={onClose} />
    </QueryClientProvider>,
  );
  return { onClose };
}

const box = (name: RegExp) => screen.getByRole("checkbox", { name }) as HTMLInputElement;
const deactivate = () => screen.getByRole("button", { name: "Deactivate" }) as HTMLButtonElement;

describe("PersonSheet", () => {
  it("shows Licensing only while Loan officer is ticked", () => {
    renderSheet(ELENA);
    expect(screen.queryByLabelText("NMLS ID")).toBeNull();
    fireEvent.click(box(/Loan officer/));
    expect(screen.getByLabelText("NMLS ID")).toBeTruthy();
    fireEvent.click(box(/Loan officer/));
    expect(screen.queryByLabelText("NMLS ID")).toBeNull();
  });

  it("disables every role box and Deactivate on your own row, saying why", () => {
    renderSheet(ME);
    for (const name of [/^Admin/, /Loan officer/, /^Processor/])
      expect(box(name).disabled).toBe(true);
    expect(deactivate().disabled).toBe(true);
    expect(screen.getAllByText("You can't change your own roles").length).toBeGreaterThan(0);
    expect(screen.getByText("You can't deactivate yourself")).toBeTruthy();
    // Your own details stay editable.
    expect((screen.getByLabelText("Title") as HTMLInputElement).disabled).toBe(false);
  });

  it("disables Deactivate and the Admin box on the owner's row, and nothing else", () => {
    renderSheet(OWNER);
    expect(box(/^Admin/).disabled).toBe(true);
    expect(box(/Loan officer/).disabled).toBe(false);
    expect(box(/^Processor/).disabled).toBe(false);
    expect(deactivate().disabled).toBe(true);
    expect(
      screen.getAllByText("This is the account owner. Contact MortgageBoss to change their access.")
        .length,
    ).toBe(2);
  });

  it("enables everything for someone else", () => {
    renderSheet(ELENA);
    for (const name of [/^Admin/, /Loan officer/, /^Processor/])
      expect(box(name).disabled).toBe(false);
    expect(deactivate().disabled).toBe(false);
  });

  it("saves only the details that changed, then the full role set", async () => {
    api.patch.mockResolvedValue({ data: { ...ELENA, title: "Senior Processor" } });
    api.put.mockResolvedValue({ data: { ...ELENA, roles: ["loan_officer", "processor"] } });
    const { onClose } = renderSheet(ELENA);

    fireEvent.change(screen.getByLabelText("Title"), { target: { value: "Senior Processor" } });
    fireEvent.click(box(/Loan officer/));
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(api.patch).toHaveBeenCalledWith(`/api/v1/users/${ELENA.id}`, {
      title: "Senior Processor",
    });
    expect(api.put).toHaveBeenCalledWith(`/api/v1/users/${ELENA.id}/roles`, {
      roles: ["processor", "loan_officer"],
    });
  });

  it("sends no role request when only details changed", async () => {
    api.patch.mockResolvedValue({ data: { ...ELENA, phone: "555" } });
    renderSheet(ELENA);
    fireEvent.change(screen.getByLabelText("Phone"), { target: { value: "555" } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(api.patch).toHaveBeenCalled());
    expect(api.put).not.toHaveBeenCalled();
  });

  it("shows the server's 409 inline at the top and stays open", async () => {
    const owner = "This is the account owner. Contact MortgageBoss to change their access.";
    api.put.mockRejectedValue(refusal(409, owner));
    // A row the UI did not know was the owner's: the server is the one that refuses.
    const { onClose } = renderSheet(person({ id: "p-x", roles: ["admin"] }));

    fireEvent.click(box(/^Admin/));
    fireEvent.click(box(/^Processor/));
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    expect((await screen.findByRole("alert")).textContent).toBe(owner);
    expect(onClose).not.toHaveBeenCalled();
  });
});
