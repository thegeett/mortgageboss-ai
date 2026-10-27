import type { MessageDetail, OutboundDraft } from "@/lib/types/communication";
import { describe, expect, it } from "vitest";
import { mailtoUrl, messageMailtoUrl } from "./communications";

/**
 * LP-991 — a company with no mail domain has no file address, so `suggested_bcc` is null. The
 * mailto link then carries no bcc at all — not `bcc=null`, which `URLSearchParams` would write.
 */
const DRAFT = {
  subject: "Documents",
  mailto_available: true,
  mailto_max_chars: 1800,
} as OutboundDraft;

const MESSAGE = {
  subject: "Documents",
  mailto_available: true,
  mailto_max_chars: 1800,
} as MessageDetail;

describe("the mailto link", () => {
  it("bccs the file address when there is one", () => {
    const url = mailtoUrl(
      { ...DRAFT, suggested_bcc: "lf-y36e@mb-mail.localhost" },
      "a@b.test",
      "Hi",
    );
    expect(url).toContain("bcc=lf-y36e%40mb-mail.localhost");
  });

  it("has no bcc when the company has no mail domain", () => {
    for (const url of [
      mailtoUrl({ ...DRAFT, suggested_bcc: null }, "a@b.test", "Hi"),
      messageMailtoUrl({ ...MESSAGE, suggested_bcc: null }, "a@b.test", "Hi"),
    ]) {
      expect(url).toBe("mailto:a%40b.test?subject=Documents&body=Hi");
    }
  });
});
