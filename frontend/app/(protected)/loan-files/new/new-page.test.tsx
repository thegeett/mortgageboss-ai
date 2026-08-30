// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

// Stub the heavy children (their deps are tested elsewhere) so this test focuses
// on the page's ranking of the two paths.
vi.mock("@/components/intake/mismo-upload", () => ({
  MismoUpload: () => <div data-testid="mismo-upload">MISMO upload</div>,
}));
vi.mock("@/components/intake/intake-form", () => ({
  IntakeForm: () => <div data-testid="intake-form">Manual form</div>,
}));

import NewLoanFilePage from "./page";

afterEach(cleanup);

/**
 * These two tests used to pin a TOGGLE: manual entry replaced the dropzone and
 * "Create manually" revealed it. LP-UI-023 removed the toggle — ranking two
 * options is a matter of order and weight, not of concealment, and hiding the
 * primary path behind a decision made before either was visible is the opposite
 * of ranking them.
 *
 * The property is unchanged and is what these still assert: the MISMO drop is
 * the primary way in and the form is secondary. Only what "secondary" means in
 * markup changed — below, not hidden.
 */
describe("New loan file page — MISMO primary, manual secondary", () => {
  it("offers both ways in on one page", () => {
    render(<NewLoanFilePage />);
    expect(screen.getByTestId("mismo-upload")).toBeDefined();
    expect(screen.getByTestId("intake-form")).toBeDefined();
  });

  it("puts the MISMO drop first — the ranking IS the order", () => {
    render(<NewLoanFilePage />);
    const upload = screen.getByTestId("mismo-upload");
    const form = screen.getByTestId("intake-form");
    // Node.compareDocumentPosition: FOLLOWING means `form` comes after `upload`.
    expect(upload.compareDocumentPosition(form) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("says a sparse file is allowed before asking for one", () => {
    // Discovered inside the form, "only the name is required" is a surprise;
    // said before it, it is what makes the form approachable.
    render(<NewLoanFilePage />);
    expect(screen.getByText(/Only the borrower.s first and last name are required/)).toBeDefined();
  });

  it("no longer hides either path behind a choice", () => {
    render(<NewLoanFilePage />);
    expect(screen.queryByRole("button", { name: /create manually/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /upload a mismo file instead/i })).toBeNull();
    // Positive control: the page rendered, so the absences above are real.
    expect(screen.getByTestId("mismo-upload")).toBeDefined();
  });
});
