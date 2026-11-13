// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PeopleTable } from "./people-table";
import { AISHA, ELENA, ME, OWNER } from "./test-people";

afterEach(cleanup);

function renderTable() {
  const onOpen = vi.fn();
  render(<PeopleTable people={[OWNER, ME, ELENA, AISHA]} currentUserId={ME.id} onOpen={onOpen} />);
  return { onOpen };
}

const names = () =>
  screen
    .getAllByRole("row")
    .slice(1)
    .map((row) => within(row).getAllByRole("cell")[0]?.textContent);

describe("PeopleTable", () => {
  it("lists active people with roles, the owner marker and (you)", () => {
    renderTable();
    expect(names()).toEqual(["Priya Desai", "Marcus Hill (you)", "Elena Ruiz"]);
    expect(screen.getByText("· owner")).toBeTruthy();
    // In the table only: the role select has an "Admin" option too.
    expect(within(screen.getByRole("table")).getAllByText("Admin")).toHaveLength(2);
    expect(screen.getByText("3 active, 1 inactive.")).toBeTruthy();
  });

  it("shows inactive people only with the toggle", () => {
    renderTable();
    expect(screen.queryByText("Aisha Khan")).toBeNull();
    fireEvent.click(screen.getByLabelText("Show inactive"));
    expect(screen.getByText("Aisha Khan")).toBeTruthy();
    expect(screen.getByText("Inactive")).toBeTruthy();
  });

  it("filters by search and by role", () => {
    renderTable();
    fireEvent.change(screen.getByLabelText("Search name or email"), { target: { value: "elena" } });
    expect(names()).toEqual(["Elena Ruiz"]);
    fireEvent.change(screen.getByLabelText("Search name or email"), { target: { value: "" } });
    fireEvent.change(screen.getByLabelText("Role"), { target: { value: "admin" } });
    expect(names()).toEqual(["Priya Desai", "Marcus Hill (you)"]);
  });

  it("opens a person from their row", () => {
    const { onOpen } = renderTable();
    fireEvent.click(screen.getByText("Elena Ruiz"));
    expect(onOpen).toHaveBeenCalledWith(ELENA);
  });
});
