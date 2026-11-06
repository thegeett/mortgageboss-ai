// @vitest-environment jsdom
import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/inbound", () => ({
  useFileMessages: () => ({
    data: [{ id: "msg-1" }, { id: "msg-2" }],
    isPending: false,
    isError: false,
  }),
}));
vi.mock("@/components/file/communication/inbound-message-card", () => ({
  InboundMessageCard: ({ message }: { message: { id: string } }) => (
    <article id={`email-${message.id}`} />
  ),
}));

import { InboundMessagesPanel } from "./inbound-messages-panel";

afterEach(() => {
  cleanup();
  window.location.hash = "";
  vi.restoreAllMocks();
});

describe("a link to an email (LP-1009)", () => {
  it("scrolls to the email it names once the list has loaded", () => {
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    window.location.hash = "#email-msg-2";
    render(<InboundMessagesPanel fileId="file-1" />);
    expect(scroll).toHaveBeenCalledTimes(1);
    expect((scroll.mock.instances[0] as unknown as Element).id).toBe("email-msg-2");
  });

  it("does not scroll with no such link", () => {
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    render(<InboundMessagesPanel fileId="file-1" />);
    expect(scroll).not.toHaveBeenCalled();
  });
});
