// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { EmptyState } from "./empty-state";

afterEach(cleanup);

describe("EmptyState", () => {
  it("says what goes here and offers the action that fills it", () => {
    render(
      <EmptyState
        kind="nothing-yet"
        title="No loan files yet"
        action={<button type="button">Create</button>}
      >
        A file holds the documents for one loan.
      </EmptyState>,
    );
    expect(screen.getByText("No loan files yet")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Create" })).toBeTruthy();
  });

  it("REFUSES an action on a structurally-empty state", () => {
    // Correct-to-be-empty means there is nothing to do. A button would say there
    // is, and send a processor looking for work that does not exist. Enforced
    // rather than left to each caller to remember.
    render(
      <EmptyState
        kind="structural"
        title="Nothing here, and that's correct"
        action={<button type="button">Add one</button>}
      >
        Rules that don&apos;t apply to this file are never recorded.
      </EmptyState>,
    );
    expect(screen.getByText("Nothing here, and that's correct")).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("gives the three kinds different glyphs, so they do not read alike", () => {
    // The distinction is the whole point of the component; if all three looked
    // the same, a processor who filtered to nothing would read "you have none".
    const icons = (["nothing-yet", "filtered", "structural"] as const).map((kind) => {
      cleanup();
      const { container } = render(
        <EmptyState kind={kind} title="t">
          body
        </EmptyState>,
      );
      return container.querySelector("svg")?.getAttribute("class") ?? "";
    });
    expect(new Set(icons).size).toBe(3);
  });

  it("renders without an action at all", () => {
    render(
      <EmptyState kind="filtered" title="No files match">
        Nothing matches.
      </EmptyState>,
    );
    expect(screen.queryByRole("button")).toBeNull();
  });
});
