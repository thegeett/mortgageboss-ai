/**
 * What a ✦ polish refusal says to a processor (LP-856).
 *
 * IT FAILS VISIBLY OR NOT AT ALL. Each of these names what happened and leaves no doubt that the
 * text is unchanged — a silent degradation is worse than an error here, because the processor
 * cannot tell which version they are looking at.
 *
 * A REFUSED REWRITE IS NOT A BUG REPORT. "The model wrote something it should not have" is our
 * problem, not theirs; what they need to know is that their words are untouched and they can try
 * again or leave it. So the guard reasons collapse into one sentence rather than being spelled out
 * — `invented_date:friday` on screen would invite them to wonder what they did wrong.
 */
export function polishMessage(refusal: string): string {
  if (refusal === "unavailable") {
    // LP-858 §5 — THIS IS NOW A RACE, NOT THE ORDINARY CASE. The button is hidden when the
    // capability says polish is not wired, so reaching this means the answer changed underneath a
    // page already open, or the request failed. The old wording named the ENVIRONMENT as the
    // reason, which is a permanent state a processor can do nothing about and reads as breakage;
    // what is true in the case that survives is that it did not run and nothing moved.
    //
    // LP-858 REVIEW — AND IT PROMISES NO RETRY, because this string has THREE producers and they
    // do not agree about whether one would help. `polish()` returns `unavailable` when
    // `email_draft_enabled` is off, which is permanent; it returns the same word on a transport
    // failure, and the client uses it again for a failed request, both of which are transient.
    // "Try again in a moment" was true of the last two and false of the first — the same shape as
    // the wording it replaced, inverted: that one asserted a permanent state, this one asserted a
    // passing one. What every producer agrees on is that it did not run and the text did not move,
    // so that is all this says. The processor can retry or leave it; neither is promised.
    return "Polish didn’t run — your message is unchanged.";
  }
  if (refusal === "empty") {
    return "There is nothing to polish yet.";
  }
  return "The rewrite added something that was not in your message, so it was discarded. Your text is unchanged.";
}
