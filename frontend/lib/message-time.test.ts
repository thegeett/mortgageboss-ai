import {
  messageInstant,
  messageTimeFull,
  messageTimeLabel,
  messageTimeShort,
} from "@/lib/message-time";
import { describe, expect, it } from "vitest";

/**
 * LP-838 — every surface that lists or opens a message says WHEN, and says the same thing.
 *
 * This module exists because "every surface" is the sentence that produces four date formats and one
 * of them wrong. It already had two: `timeline-panel.tsx` and `message-dialog.tsx` each declared a
 * local `when()` — same name, different behaviour, and neither said what its time was.
 */
describe("messageInstant — the server's rule, not a second one", () => {
  it("prefers sent_at", () => {
    // `services/timeline.py::_message_at`: a draft composed on Monday and sent on Thursday belongs
    // at Thursday, because that is when the borrower heard from us. The list is ORDERED by that
    // value server-side, so a client displaying a different instant would sort by one and label by
    // another — which shows up as a list that looks mis-sorted.
    expect(
      messageInstant({ sent_at: "2026-09-04T10:00:00Z", created_at: "2026-09-01T10:00:00Z" }),
    ).toBe("2026-09-04T10:00:00Z");
  });

  it("falls back to created_at", () => {
    expect(messageInstant({ sent_at: null, created_at: "2026-09-01T10:00:00Z" })).toBe(
      "2026-09-01T10:00:00Z",
    );
  });
});

describe("messageTimeLabel — what the instant IS", () => {
  it("says Created for a draft", () => {
    // The request asked for "when it was created", which for a draft is exactly this.
    expect(messageTimeLabel({ direction: "outbound", status: "draft" })).toBe("Created");
  });

  it("says Sent once it has gone", () => {
    // And `created` would now be the wrong word for the time being shown, which is `sent_at`.
    expect(messageTimeLabel({ direction: "outbound", status: "sent" })).toBe("Sent");
  });

  it("says Failed rather than Sent for a failed send", () => {
    // ITS INSTANT IS `sent_at`, so the obvious implementation labels it "Sent" — which is the one
    // thing that did not happen. LP-819 gave delivery failure its own activity type for this reason.
    expect(messageTimeLabel({ direction: "outbound", status: "failed" })).toBe("Failed");
  });

  it("says Received for inbound", () => {
    expect(messageTimeLabel({ direction: "inbound", status: "received" })).toBe("Received");
  });

  it("survives a timeline row with no direction", () => {
    // `TimelineEntry` types both as nullable. An unlabelled time is better than a wrong label, and
    // better than a crash on a shape the server is allowed to send.
    expect(messageTimeLabel({ direction: null, status: null })).toBe("Created");
  });
});

describe("the two presentations", () => {
  it("are the same instant, formatted differently", () => {
    // THE CLAIM THIS MODULE IS FOR, asserted from ONE value — which is the only way it means
    // anything. Two formatters given two values would agree by coincidence.
    const iso = "2026-09-04T14:30:00Z";

    expect(messageTimeFull(iso)).toContain("4 Sep 2026");
    expect(messageTimeShort(iso)).toMatch(/ago$/);
  });

  it("render nothing rather than Invalid Date", () => {
    // Both the timeline panel and the activity feed already guard this; a third surface should not
    // learn it in front of a processor.
    for (const bad of ["", null, undefined, "not-a-date"]) {
      expect(messageTimeShort(bad)).toBe("");
      expect(messageTimeFull(bad)).toBe("");
    }
  });

  it("the short form is short and the full form is not", () => {
    // THE CONTROL. Two functions that returned the same string would pass every assertion above,
    // and the distinction — a list is scanned, one open message is read — is the whole point.
    const iso = "2026-09-04T14:30:00Z";

    expect(messageTimeShort(iso)).not.toBe(messageTimeFull(iso));
  });
});

describe("no surface keeps its own format", () => {
  it("nothing under components/file/communication formats a message time itself", async () => {
    // LP-838 — THE CLASS, ASSERTED RATHER THAN DESCRIBED. "Every surface that lists or opens a
    // message" is the sentence that produces four date formats and one of them wrong, and it had
    // already produced three: two functions both called `when` with different behaviour, and a
    // `toLocaleString()` on the inbound card — on the same page, none wrong on its own.
    //
    // A fourth surface inherits the rule by failing this rather than by somebody remembering.
    const { readdirSync, readFileSync } = await import("node:fs");
    const dir = new URL("../components/file/communication/", import.meta.url).pathname;

    const offenders = readdirSync(dir)
      .filter((name) => name.endsWith(".tsx") && !name.endsWith(".test.tsx"))
      .filter((name) => {
        // COMMENTS STRIPPED FIRST. This test is about what the code DOES, and the comment explaining
        // why `toLocaleString()` was removed from the inbound card matched the scan and reported the
        // file it had just fixed. A guard that fires on prose about itself is a guard nobody keeps.
        const source = readFileSync(`${dir}${name}`, "utf8")
          .replace(/\/\*[\s\S]*?\*\//g, "")
          .replace(/^\s*\/\/.*$/gm, "");
        return (
          source.includes("toLocaleString()") ||
          source.includes("formatDistanceToNow") ||
          /format\(new Date/.test(source)
        );
      });

    expect(offenders).toEqual([
      // The one legitimate exception, and it is not a message: an upload link's EXPIRY is a
      // deadline, not a thing that happened, and "Expires in 2 days" is not a sentence
      // `message-time` should learn to say.
      "upload-link-panel.tsx",
    ]);
  });
});
