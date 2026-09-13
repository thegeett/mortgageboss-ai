/**
 * LP-858 REVIEW — what a ✦ polish refusal says, pinned.
 *
 * THIS COPY HAD NO TEST AND THREE PRODUCERS. `polish()` returns `unavailable` when
 * `email_draft_enabled` is off, returns it again on a transport failure, and the dialog uses it a
 * third time for a failed request. Nothing asserted the sentence any of them produce, so a wording
 * that was true of one and false of another read exactly like one that was true of all three.
 */
import { describe, expect, it } from "vitest";
import { polishMessage } from "./polish-messages";

describe("polishMessage", () => {
  it("says what happened and that the text did not move", () => {
    for (const refusal of ["unavailable", "empty", "invented_date:friday"]) {
      const message = polishMessage(refusal);
      expect(message.length).toBeGreaterThan(0);
      expect(message).not.toContain("_"); // no guard reason leaks to the screen
    }
  });

  it("names the unchanged text on every refusal a rewrite can produce", () => {
    // "Their words are untouched" is the one thing a processor needs from every one of these, and
    // the `empty` case is the exception that proves it: there was nothing to change.
    expect(polishMessage("unavailable")).toContain("unchanged");
    expect(polishMessage("invented_date:friday")).toContain("unchanged");
    expect(polishMessage("empty")).toContain("nothing to polish");
  });

  it("promises no retry on `unavailable`, because one of its three producers is permanent", () => {
    // THE FINDING THIS FILE EXISTS FOR. `email_draft_enabled` being off produces `unavailable` and
    // is permanent — retrying never helps. A transport failure and a failed request produce the
    // same word and are transient. "Try again in a moment" was true of the last two and false of
    // the first, which is the wording it replaced with the error inverted: that one asserted a
    // permanent state, this one asserted a passing one.
    const message = polishMessage("unavailable");

    expect(message).not.toMatch(/try again|in a moment|shortly|retry/i);
    // THE CONTROL: the matcher does catch a retry promise, so "does not match" above is about the
    // sentence rather than about a pattern that never fires.
    expect("Polish didn’t run. Try again in a moment.").toMatch(/try again|in a moment/i);
  });

  it("does not name the environment either, which is what it used to do", () => {
    // The refusal a processor cannot act on. Absent in both directions now: no permanent claim, no
    // transient one.
    expect(polishMessage("unavailable")).not.toMatch(/environment|not available|disabled/i);
  });
});
