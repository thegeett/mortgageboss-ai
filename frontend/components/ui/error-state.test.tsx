// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ErrorState, InlineErrorState } from "./error-state";

afterEach(cleanup);

describe("ErrorState", () => {
  it("renders the message and a Retry that calls onRetry", () => {
    const onRetry = vi.fn();
    render(<ErrorState title="Couldn’t load your documents" message="boom" onRetry={onRetry} />);
    expect(screen.getByText("Couldn’t load your documents")).toBeDefined();
    expect(screen.getByRole("alert")).toBeDefined();
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("omits the Retry button when no onRetry is given", () => {
    render(<ErrorState message="no retry here" />);
    expect(screen.queryByRole("button")).toBeNull();
  });
});

describe("InlineErrorState", () => {
  it("renders an inline Retry that calls onRetry", () => {
    const onRetry = vi.fn();
    render(<InlineErrorState message="Couldn't load activity." onRetry={onRetry} />);
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(onRetry).toHaveBeenCalledOnce();
  });
});
