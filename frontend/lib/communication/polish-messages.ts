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
    return "Polish is not available on this environment — your message is unchanged.";
  }
  if (refusal === "empty") {
    return "There is nothing to polish yet.";
  }
  return "The rewrite added something that was not in your message, so it was discarded. Your text is unchanged.";
}
