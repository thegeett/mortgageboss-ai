// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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

describe("PersonSheet — licensed states (review finding 9)", () => {
  it("adds a real state code and refuses a made-up one as it is typed", () => {
    renderSheet(person({ roles: ["loan_officer"] }));
    const input = screen.getByLabelText("Licensed states");

    fireEvent.change(input, { target: { value: "nj" } });
    fireEvent.keyDown(input, { key: "Enter" });
    fireEvent.change(input, { target: { value: "XX" } });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(screen.getByText("NJ")).toBeTruthy();
    expect(screen.getByText("XX is not a US state code.")).toBeTruthy();
    expect(screen.queryByText("XX", { selector: "div" })).toBeNull();
    expect((input as HTMLInputElement).value).toBe("XX");
  });
});

describe("PersonSheet — deactivating someone who works files (LP-MB-Admin-05)", () => {
  it("shows no file section for someone with no files", async () => {
    renderSheet(person({ id: "p-x", file_count: 0 }));
    fireEvent.click(screen.getByRole("button", { name: "Deactivate" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).queryByText(/They are on/)).toBeNull();
    expect(within(dialog).getByRole("button", { name: "Deactivate" })).toBeTruthy();
  });

  it("moves their files first, then deactivates", async () => {
    const calls: string[] = [];
    api.get.mockImplementation(async (url: string) =>
      url === "/api/v1/users/assignable"
        ? { data: [{ id: "p-tom", name: "Tom Becker", roles: ["processor"], file_count: 6 }] }
        : { data: EMPTY_PAGE },
    );
    api.post.mockImplementation(async (url: string) => {
      calls.push(url);
      return url.endsWith("/reassign-loans")
        ? { data: { moved: 14 } }
        : { data: { ...ELENA, is_active: false, file_count: 0 } };
    });
    renderSheet(person({ file_count: 14, team_slots: ["processor"] }));

    fireEvent.click(screen.getByRole("button", { name: "Deactivate" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("They are on 14 loan files")).toBeTruthy();
    const picker = within(dialog).getByLabelText("Move their files to");
    await waitFor(() =>
      expect(within(picker).getByText("Tom Becker · 6 files now, 20 after")).toBeTruthy(),
    );
    fireEvent.change(picker, { target: { value: "p-tom" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Deactivate and move 14 files" }));

    await waitFor(() => expect(calls).toHaveLength(2));
    expect(calls).toEqual([
      `/api/v1/users/${ELENA.id}/reassign-loans`,
      `/api/v1/users/${ELENA.id}/deactivate`,
    ]);
    expect(api.post.mock.calls[0]?.[1]).toEqual({ to_user_id: "p-tom" });
  });

  it("leaves their files when asked, and only deactivates", async () => {
    api.get.mockImplementation(async (url: string) =>
      url === "/api/v1/users/assignable" ? { data: [] } : { data: EMPTY_PAGE },
    );
    api.post.mockResolvedValue({ data: { ...ELENA, is_active: false } });
    renderSheet(person({ file_count: 3, team_slots: ["processor"] }));

    fireEvent.click(screen.getByRole("button", { name: "Deactivate" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByLabelText(/Leave their files as they are/));
    fireEvent.click(within(dialog).getByRole("button", { name: "Deactivate" }));

    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
    expect(api.post).toHaveBeenCalledWith(`/api/v1/users/${ELENA.id}/deactivate`);
  });
});

describe("PersonSheet — review fixes (LP-MB-Admin-05)", () => {
  it("offers only people eligible for every slot the files need (finding 2)", async () => {
    api.get.mockImplementation(
      async (url: string, config?: { params?: { team_role?: string } }) => {
        if (url !== "/api/v1/users/assignable") return { data: EMPTY_PAGE };
        return config?.params?.team_role === "loan_officer"
          ? {
              data: [
                { id: "p-lo-only", name: "Lo Only", roles: ["loan_officer"], file_count: 0 },
                {
                  id: "p-both",
                  name: "Both Roles",
                  roles: ["loan_officer", "processor"],
                  file_count: 1,
                },
              ],
            }
          : {
              data: [
                { id: "p-proc-only", name: "Proc Only", roles: ["processor"], file_count: 0 },
                {
                  id: "p-both",
                  name: "Both Roles",
                  roles: ["loan_officer", "processor"],
                  file_count: 1,
                },
              ],
            };
      },
    );
    renderSheet(person({ file_count: 4, team_slots: ["loan_officer", "processor"] }));

    fireEvent.click(screen.getByRole("button", { name: "Deactivate" }));
    const picker = within(await screen.findByRole("dialog")).getByLabelText("Move their files to");

    await waitFor(() => expect(within(picker).getByText(/Both Roles/)).toBeTruthy());
    expect(within(picker).queryByText(/Lo Only/)).toBeNull();
    expect(within(picker).queryByText(/Proc Only/)).toBeNull();
  });

  it("says the files moved when the deactivation then fails (finding 5)", async () => {
    api.get.mockImplementation(async (url: string) =>
      url === "/api/v1/users/assignable"
        ? { data: [{ id: "p-tom", name: "Tom Becker", roles: ["processor"], file_count: 0 }] }
        : { data: EMPTY_PAGE },
    );
    api.post.mockImplementation(async (url: string) => {
      if (url.endsWith("/reassign-loans")) return { data: { moved: 3 } };
      throw refusal(409, "This is the account owner. Contact MortgageBoss to change their access.");
    });
    renderSheet(person({ file_count: 3, team_slots: ["processor"] }));

    fireEvent.click(screen.getByRole("button", { name: "Deactivate" }));
    const dialog = await screen.findByRole("dialog");
    const picker = within(dialog).getByLabelText("Move their files to");
    await waitFor(() => expect(within(picker).getByText(/Tom Becker/)).toBeTruthy());
    fireEvent.change(picker, { target: { value: "p-tom" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Deactivate and move 3 files" }));

    expect((await screen.findByRole("alert")).textContent).toBe(
      "Their 3 files were moved, but they could not be deactivated: This is the account owner. Contact MortgageBoss to change their access.",
    );
  });
});
