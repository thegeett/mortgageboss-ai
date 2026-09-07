import { format, formatDistanceToNow } from "date-fns";

/**
 * When a message happened, said the same way everywhere (LP-838).
 *
 * ONE MODULE BECAUSE "EVERY SURFACE THAT LISTS OR OPENS A MESSAGE" IS THE SENTENCE THAT PRODUCES
 * FOUR DATE FORMATS AND ONE OF THEM WRONG. It already had: `timeline-panel.tsx` and
 * `message-dialog.tsx` each declared a local function called `when`, same name, different behaviour
 * — one relative, one absolute — and neither said what its time WAS.
 *
 * THE INSTANT IS THE SERVER'S, NOT RECOMPUTED HERE. `services/timeline.py::_message_at` decides that
 * a message belongs at `sent_at` when there is one and `created_at` otherwise: *"a draft composed on
 * Monday and sent on Thursday belongs at Thursday — that is when the borrower heard from us."* The
 * list is ordered by that value on the server, so a client that picked a different instant to DISPLAY
 * would sort by one and label by another, and the disagreement would show up as a list that looks
 * mis-sorted. `messageInstant` exists only for surfaces holding a message rather than a timeline row.
 */

/** Which instant a message belongs at — the same rule `_message_at` applies on the server. */
export function messageInstant(message: { sent_at?: string | null; created_at: string }): string {
  return message.sent_at ?? message.created_at;
}

/**
 * What that instant IS, in a word.
 *
 * A BARE TIMESTAMP BESIDE A MESSAGE IS AMBIGUOUS IN EXACTLY THE WAY THAT MATTERS: a draft composed
 * on Monday and sent on Thursday shows Thursday, and "Thursday" alone does not say whether the
 * borrower has heard from us. The request that started this asked for "when it was created", which
 * for a draft is what this returns — and once a message is sent, `created` would be the wrong word
 * for the time being shown.
 *
 * FAILED IS ITS OWN WORD. Its instant is `sent_at`, so it would read as "Sent" — which is the one
 * thing that did not happen. LP-819 gave delivery failure its own activity type for the same reason.
 *
 * "LAST CHANGED" IS NOT AVAILABLE AND IS NOT GUESSED AT. `Communication` has no `updated_at`, and a
 * draft is regenerated on every add and remove — so a draft edited an hour ago still says created,
 * truthfully, and adding `updated_at` is a migration and a decision this does not make.
 */
export function messageTimeLabel(message: {
  direction: string | null;
  status: string | null;
}): string {
  // NULLABLE ON A TIMELINE ROW, and typed that way rather than asserted away. `TimelineEntry`
  // declares both as `string | null` — LP-825 left the shape wide enough for a kind that is not a
  // message, and narrowing here with a cast would be the client deciding something the server did
  // not say. An unlabelled time is better than a wrong label.
  if (message.direction === "inbound") return "Received";
  if (message.status === "sent" || message.status === "delivered") return "Sent";
  if (message.status === "failed") return "Failed";
  return "Created";
}

/**
 * The short form, for a list — what an email client shows.
 *
 * A column of full timestamps is unreadable at a glance, which is the one thing a list is for.
 * Returns the empty string rather than "Invalid Date" on an unparseable value: both the timeline
 * panel and the activity feed already guard this, and a third surface should not learn it the hard
 * way in front of a processor.
 */
export function messageTimeShort(iso: string | null | undefined): string {
  if (!iso) return "";
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return "";
  return formatDistanceToNow(at, { addSuffix: true });
}

/**
 * The full form, for one message a processor has opened.
 *
 * Somebody reading one message is looking at that message, and "yesterday" is not enough to put in a
 * note or an audit conversation. Same instant as the short form; only the presentation differs.
 */
export function messageTimeFull(iso: string | null | undefined): string {
  if (!iso) return "";
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return "";
  return format(at, "d MMM yyyy, HH:mm");
}
