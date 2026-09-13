// @vitest-environment jsdom
/**
 * LP-857 — the Communication page offers only what this version can do.
 *
 * ACCEPTANCE 1 AND 4. Every assertion here is a not-in over a page that is mostly absences, so each
 * one is paired with the state where the thing IS there: the panels render with the flag on, and
 * the two buttons that remain are asserted by name rather than by count alone.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mockCapabilities = vi.fn();
vi.mock("@/lib/api/capabilities", () => ({ useCapabilities: () => mockCapabilities() }));
vi.mock("next/navigation", () => ({ useParams: () => ({ id: "LF-JR4T" }) }));

// The three children are stubbed to their identity. What this file is about is WHICH of them the
// page mounts; what each one does is covered in its own suite.
vi.mock("@/components/file/communication/timeline-panel", () => ({
  TimelinePanel: () => <div data-testid="timeline" />,
}));
vi.mock("@/components/file/communication/upload-link-panel", () => ({
  UploadLinkPanel: () => <div data-testid="upload-link" />,
}));
vi.mock("@/components/file/communication/inbound-messages-panel", () => ({
  InboundMessagesPanel: () => <div data-testid="inbound" />,
}));
vi.mock("@/components/file/communication/compose-request-button", () => ({
  ComposeRequestButton: () => <button type="button">Request documents</button>,
}));
vi.mock("@/components/file/communication/compose-draft-dialog", () => ({
  ComposeDraftButton: () => <button type="button">Compose</button>,
}));

import CommunicationPage from "./page";

afterEach(cleanup);
beforeEach(() => vi.clearAllMocks());

function withReceiving(receiving: boolean | undefined) {
  mockCapabilities.mockReturnValue({ data: receiving === undefined ? undefined : { receiving } });
  render(<CommunicationPage />);
}

describe("the Communication page", () => {
  it("offers exactly two buttons: Request documents and Compose", () => {
    // ACCEPTANCE 1. BY NAME AND BY COUNT. The names alone would pass with a third button beside
    // them; the count alone would pass if one were swapped for something else.
    withReceiving(false);

    const buttons = screen.getAllByRole("button").map((b) => b.textContent);
    expect(buttons).toEqual(["Compose", "Request documents"]);
  });

  it("does not offer Write to another party", () => {
    // The one control this ticket REMOVES rather than flags. Asserted by its own words: the button
    // is gone, and so is the module it opened — a re-import would fail the build before this runs.
    withReceiving(false);

    expect(screen.queryByText(/another party/i)).toBeNull();
  });

  it("hides the upload link and inbound mail while the version cannot receive", () => {
    // ACCEPTANCE 4. Unreachable, not deleted — the components still compile and their own suites
    // still run, which is what stops the flag from being a deletion with extra steps.
    withReceiving(false);

    expect(screen.queryByTestId("upload-link")).toBeNull();
    expect(screen.queryByTestId("inbound")).toBeNull();
    // And the page is not simply empty: the list is the screen.
    expect(screen.getByTestId("timeline")).toBeTruthy();
  });

  it("shows them again when the version can receive", () => {
    // THE POSITIVE CONTROL for both absences above. Without it they pass against a page that mounts
    // neither panel under any condition, against a broken import, and against a stub that renders
    // nothing.
    withReceiving(true);

    expect(screen.getByTestId("upload-link")).toBeTruthy();
    expect(screen.getByTestId("inbound")).toBeTruthy();
  });

  it("hides them while the answer has not arrived", () => {
    // FALSE IS THE SAFE DEFAULT. A panel that flashed in before the capability resolved would be a
    // control a processor could click on a version where the thing behind it does not exist.
    withReceiving(undefined);

    expect(screen.queryByTestId("upload-link")).toBeNull();
    expect(screen.queryByTestId("inbound")).toBeNull();
  });
});
