import { describe, expect, it } from "vitest";
import {
  CHECK_EVERY_MS,
  CONFIRM_WINDOW_MS,
  type SendState,
  checkInterval,
  sendStatusLabel,
} from "./send-status";

const SENT_AT = "2026-10-31T12:00:00Z";
const T0 = Date.parse(SENT_AT);

function send(over: Partial<SendState>): SendState {
  return { status: "queued", errorDetail: null, requestedAt: SENT_AT, ...over };
}

describe("sendStatusLabel (LP-997)", () => {
  it.each([
    ["queued", null, "Queued"],
    ["sending", null, "Sending"],
    ["sent", null, "Sent"],
    ["delivered", null, "Delivered"],
    ["failed", null, "Failed"],
    ["failed", "", "Failed"],
    // A reason that already says what happened is shown on its own, not as "Failed: Not …".
    [
      "failed",
      "Not delivered: this address bounced or complained before. Ask the borrower for another address.",
      "Not delivered: this address bounced or complained before. Ask the borrower for another address.",
    ],
    [
      "failed",
      "Not sent: SES refused it (Bad content).",
      "Not sent: SES refused it (Bad content).",
    ],
    ["failed", "smtp; 550 5.1.1 user unknown", "Failed: smtp; 550 5.1.1 user unknown"],
  ])("%s with %j reads %j", (status, errorDetail, label) => {
    expect(sendStatusLabel(send({ status, errorDetail }), T0 + 1_000)).toBe(label);
  });

  it("reads Not confirmed once a Send has been with the worker for 1.5 minutes", () => {
    // The positive control: the same Send a moment earlier is still Queued.
    expect(sendStatusLabel(send({}), T0 + CONFIRM_WINDOW_MS - 1)).toBe("Queued");
    expect(sendStatusLabel(send({}), T0 + CONFIRM_WINDOW_MS)).toBe(
      "Not confirmed: check before sending again",
    );
    expect(sendStatusLabel(send({ status: "sending" }), T0 + CONFIRM_WINDOW_MS)).toBe(
      "Not confirmed: check before sending again",
    );
  });

  it("does not time out a Send that went", () => {
    expect(sendStatusLabel(send({ status: "sent" }), T0 + 10 * CONFIRM_WINDOW_MS)).toBe("Sent");
  });

  it("reads Not confirmed at once when the worker said so", () => {
    expect(
      sendStatusLabel(send({ status: "sending", errorDetail: "Not confirmed: TimeoutError" }), T0),
    ).toBe("Not confirmed: check before sending again");
  });

  it("never times out an automatic reply, which has no send time", () => {
    expect(sendStatusLabel(send({ requestedAt: null }), T0 + 10 * CONFIRM_WINDOW_MS)).toBe(
      "Queued",
    );
  });

  it("leaves drafts and inbound messages to their existing wording", () => {
    expect(sendStatusLabel(send({ status: "draft", requestedAt: null }))).toBeNull();
    expect(sendStatusLabel(send({ status: "received", requestedAt: null }))).toBeNull();
  });
});

describe("checkInterval (LP-997)", () => {
  it("checks every 30 seconds for 1.5 minutes after Send, then stops", () => {
    expect(CHECK_EVERY_MS).toBe(30_000);
    expect(CONFIRM_WINDOW_MS).toBe(90_000);
    expect(checkInterval([send({})], T0)).toBe(30_000);
    expect(checkInterval([send({})], T0 + 60_000)).toBe(30_000);
    expect(checkInterval([send({})], T0 + 90_000)).toBe(false);
  });

  it.each(["sent", "delivered", "failed"])("stops once it is %s", (status) => {
    expect(checkInterval([send({ status })], T0)).toBe(false);
  });

  it("does not check an automatic reply, or one the worker marked not confirmed", () => {
    expect(checkInterval([send({ requestedAt: null })], T0)).toBe(false);
    expect(
      checkInterval([send({ status: "sending", errorDetail: "Not confirmed: TimeoutError" })], T0),
    ).toBe(false);
    expect(checkInterval([], T0)).toBe(false);
  });
});
