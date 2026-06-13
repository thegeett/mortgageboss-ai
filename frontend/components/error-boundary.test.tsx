// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ErrorBoundary } from "./error-boundary";

afterEach(cleanup);

function Boom(): never {
  throw new Error("kaboom: /internal/secret/path");
}

describe("ErrorBoundary", () => {
  it("renders a friendly fallback (not a white screen) when a child throws", () => {
    // Silence the expected React error log for this render.
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>,
    );
    expect(screen.getByText("Something went wrong")).toBeDefined();
    expect(screen.getByRole("button", { name: /try again/i })).toBeDefined();
    // The raw error text / internal path is NEVER shown to the user.
    expect(screen.queryByText(/internal\/secret\/path/)).toBeNull();
    spy.mockRestore();
  });

  it("recovers when the child stops throwing and the user retries", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    // A closure flag (survives the boundary's remount, unlike component state).
    let shouldThrow = true;
    function Flaky() {
      if (shouldThrow) throw new Error("transient");
      return <div>Recovered content</div>;
    }

    render(
      <ErrorBoundary>
        <Flaky />
      </ErrorBoundary>,
    );
    expect(screen.getByText("Something went wrong")).toBeDefined();

    shouldThrow = false; // the next mount renders healthy
    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(screen.getByText("Recovered content")).toBeDefined();
    spy.mockRestore();
  });

  it("calls onReset when the user retries", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    const onReset = vi.fn();
    render(
      <ErrorBoundary onReset={onReset}>
        <Boom />
      </ErrorBoundary>,
    );
    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(onReset).toHaveBeenCalledOnce();
    spy.mockRestore();
  });
});
