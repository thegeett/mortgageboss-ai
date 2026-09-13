import type { MailClient } from "@/lib/api/preferences";
/**
 * LP-855 — the four compose routes.
 *
 * ACCEPTANCE 1 is "each of the four opens with To and Subject correct and the body EMPTY", and
 * ACCEPTANCE 6 is "subject and address are URL-encoded correctly, including `+`, `&` and non-ASCII
 * names". Both are about the URL, so both live here rather than in a component test.
 */
import { describe, expect, it } from "vitest";
import { composeButtonLabel, composeUrl, effectiveClient } from "./compose-routes";

const CLIENTS: MailClient[] = ["gmail", "outlook_work", "outlook_personal", "mailto"];

const ORIGIN: Record<MailClient, string> = {
  gmail: "https://mail.google.com/mail/",
  outlook_work: "https://outlook.office.com/mail/deeplink/compose",
  outlook_personal: "https://outlook.live.com/mail/0/deeplink/compose",
  mailto: "mailto:",
};

describe("every route", () => {
  it.each(CLIENTS)("%s opens with To and Subject, and an EMPTY body", (client) => {
    const url = composeUrl(client, { to: "sarah@example.com", subject: "Documents we need" });

    expect(url.startsWith(ORIGIN[client])).toBe(true);

    const query = new URLSearchParams(url.slice(url.indexOf("?") + 1));
    // FILLING THE BODY WITH STRIPPED PLAIN TEXT WOULD BE WORSE THAN LEAVING IT EMPTY: it hands the
    // processor a message that looks finished and has quietly lost its structure, and nothing
    // prompts them to notice. An empty body is obviously unfinished.
    expect(query.get("body")).toBe("");
    expect(query.get(client === "gmail" ? "su" : "subject")).toBe("Documents we need");
  });

  it.each(CLIENTS)("%s carries the address", (client) => {
    const url = composeUrl(client, { to: "sarah@example.com", subject: "s" });
    if (client === "mailto") {
      // RFC 6068 puts the address in the PATH, percent-encoded — except the `@`, which every
      // example in the RFC shows literal and every client handles. This asserted `%40`, which is
      // what `encodeURIComponent` produces and the opposite of what the code's own comment claimed.
      expect(url.slice(0, url.indexOf("?"))).toBe("mailto:sarah@example.com");
    } else {
      const query = new URLSearchParams(url.slice(url.indexOf("?") + 1));
      expect(query.get("to")).toBe("sarah@example.com");
    }
  });
});

describe("ACCEPTANCE 6 — encoding", () => {
  const AWKWARD = [
    ["an ampersand", "Smith & Sons — documents"],
    ["a plus", "Documents + the appraisal"],
    ["a non-ASCII name", "Documentos para José Álvarez"],
    ["a hash", "File #LF-JR4T"],
    ["a question mark", "Which statement?"],
    ["an equals", "Balance = $10,000"],
    ["a slash", "W-2 / 1099"],
    ["a quote", 'The "original", not a copy'],
  ] as const;

  it.each(CLIENTS)("%s round-trips every awkward subject", (client) => {
    for (const [name, subject] of AWKWARD) {
      const url = composeUrl(client, { to: "a@b.example", subject });
      const query = new URLSearchParams(url.slice(url.indexOf("?") + 1));
      const key = client === "gmail" ? "su" : "subject";
      expect(query.get(key), `${client}: ${name}`).toBe(subject);
    }
  });

  it("an ampersand does not invent a second header on the mailto route", () => {
    // `&` ends a header and starts another. Unencoded, "Smith & Sons" truncates the subject and
    // invents a header called " Sons" — which is the shape of the bug rather than a hypothetical.
    const url = composeUrl("mailto", { to: "a@b.example", subject: "Smith & Sons" });
    const query = new URLSearchParams(url.slice(url.indexOf("?") + 1));
    expect([...query.keys()].sort()).toEqual(["body", "subject"]);
    expect(query.get("subject")).toBe("Smith & Sons");
  });

  it("a non-ASCII address survives", () => {
    const url = composeUrl("mailto", { to: "josé@example.com", subject: "s" });
    const address = decodeURIComponent(url.slice("mailto:".length, url.indexOf("?")));
    expect(address).toBe("josé@example.com");
  });

  it("the address keeps a literal @, and still encodes what must be encoded", () => {
    // LP-855 REVIEW — the comment here said `encodeURIComponent` leaves `@` alone. It does not: it
    // encodes it to `%40`, so this built `mailto:p%40x.com`. Most clients decode that and some do
    // not, and the ones that do not open a compose window with an EMPTY To — which reads as the
    // button half-working rather than as an encoding problem.
    expect(composeUrl("mailto", { to: "p@x.com", subject: "s" })).toContain("mailto:p@x.com?");

    // THE OTHER HALF, and the reason this is not just "stop encoding". A plus-addressed mailbox
    // must keep its `+` encoded — a literal one is read as a space by some parsers, which silently
    // delivers to the wrong mailbox.
    expect(composeUrl("mailto", { to: "p+tag@x.com", subject: "s" })).toContain(
      "mailto:p%2Btag@x.com?",
    );
  });
});

describe("the button's label", () => {
  it("names the chosen client, so it says what will happen before it happens", () => {
    expect(composeButtonLabel("gmail")).toBe("Copy & open Gmail");
    expect(composeButtonLabel("outlook_work")).toBe("Copy & open Outlook");
    expect(composeButtonLabel("outlook_personal")).toBe("Copy & open Outlook");
  });

  it("ACCEPTANCE 5 — an unanswered picker reads 'mail app', and behaves as mailto", () => {
    // "Until they choose, the draft button reads Copy & open mail app." `null` is the unanswered
    // state, and it is not the same value as choosing the desktop default — but it behaves the
    // same, which is what makes deferring the question safe.
    expect(composeButtonLabel(null)).toBe("Copy & open mail app");
    expect(composeButtonLabel("mailto")).toBe("Copy & open mail app");
    expect(effectiveClient(null)).toBe("mailto");
    expect(effectiveClient("gmail")).toBe("gmail");
  });
});
