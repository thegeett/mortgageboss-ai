// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

// Stub the heavy children (their deps are tested elsewhere) so this test focuses
// on the page's reorientation logic (MISMO primary / manual secondary).
vi.mock("@/components/intake/mismo-upload", () => ({
  MismoUpload: () => <div data-testid="mismo-upload">MISMO upload</div>,
}));
vi.mock("@/components/intake/intake-form", () => ({
  IntakeForm: () => <div data-testid="intake-form">Manual form</div>,
}));

import NewLoanFilePage from "./page";

afterEach(cleanup);

describe("New loan file page — MISMO primary, manual secondary", () => {
  it("leads with the MISMO upload; manual form is not shown by default", () => {
    render(<NewLoanFilePage />);
    expect(screen.getByTestId("mismo-upload")).toBeDefined();
    expect(screen.getByRole("button", { name: /create manually/i })).toBeDefined();
    expect(screen.queryByTestId("intake-form")).toBeNull(); // secondary, hidden until chosen
  });

  it("reveals the manual form (and hides the upload) when 'Create manually' is chosen", () => {
    render(<NewLoanFilePage />);
    fireEvent.click(screen.getByRole("button", { name: /create manually/i }));
    expect(screen.getByTestId("intake-form")).toBeDefined();
    expect(screen.queryByTestId("mismo-upload")).toBeNull();
    // Can switch back to the (primary) MISMO upload.
    expect(screen.getByRole("button", { name: /upload a mismo file instead/i })).toBeDefined();
  });
});
