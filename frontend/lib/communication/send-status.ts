/**
 * A sent email's status in plain words (LP-997). One module, read by the timeline row and the open
 * message, so the two cannot word the same status differently or wait for it differently.
 */
import type { TimelineEntry } from "@/lib/types/timeline";
import { useEffect, useState } from "react";

/** LP-994's `NOT_CONFIRMED_PREFIX` (`app/models/communication.py`): the worker could not confirm
 * the provider took it, so it may or may not have gone. */
export const NOT_CONFIRMED_PREFIX = "Not confirmed: ";

/** Statuses that mean the worker has not finished with it yet. */
export const IN_FLIGHT_STATUSES: ReadonlySet<string> = new Set(["queued", "sending"]);

/** How often the screen re-checks a Send that is still with the worker. */
export const CHECK_EVERY_MS = 30_000;

/**
 * How long after Send the screen keeps checking: three checks, 30 seconds apart. A Send still queued
 * or sending after this reads "Still sending" and the checking stops. Nothing is changed on the
 * server: if the worker finishes it later, the next load shows the real status.
 */
export const CONFIRM_WINDOW_MS = 3 * CHECK_EVERY_MS;

const NOT_CONFIRMED_LABEL = "Not confirmed: check before sending again";

/**
 * LP-998 — A SEND STILL WITH THE WORKER AFTER THE WINDOW IS NOT "NOT CONFIRMED". A merely queued
 * email may still be sent by the worker (its re-enqueue runs every 5 minutes), so telling the
 * processor to "check before sending again" can make her send a duplicate from her own mail. Only
 * the server's own unknown outcome (`NOT_CONFIRMED_PREFIX`) says that.
 */
const STILL_SENDING_LABEL = "Still sending: check back in a few minutes";

/** Reasons that already read as a status on their own (LP-994 `record_not_sent`, LP-995 bounces). */
const SAYS_ITSELF = ["Not sent", "Not delivered"];

/** A person's Send, as the screens hold it. `requestedAt` is null for anything not sent from the app. */
export interface SendState {
  status: string | null;
  errorDetail: string | null;
  requestedAt: string | null;
}

/** LP-997 — a timeline row as a Send: `detail.send_requested_at` is null unless a person pressed Send. */
export function entrySendState(entry: TimelineEntry): SendState {
  const requestedAt = entry.detail.send_requested_at;
  const errorDetail = entry.detail.error_detail;
  return {
    status: entry.status,
    errorDetail: typeof errorDetail === "string" ? errorDetail : null,
    requestedAt: typeof requestedAt === "string" ? requestedAt : null,
  };
}

/** Milliseconds since Send, or null when it was not sent from the app or the time is unreadable. */
function sinceSend(requestedAt: string | null, now: number): number | null {
  if (!requestedAt) return null;
  const at = Date.parse(requestedAt);
  return Number.isNaN(at) ? null : now - at;
}

/** Still with the worker, and still inside the window: the screen should check again. */
export function stillChecking(send: SendState, now: number = Date.now()): boolean {
  if (!IN_FLIGHT_STATUSES.has(send.status ?? "")) return false;
  if ((send.errorDetail ?? "").startsWith(NOT_CONFIRMED_PREFIX)) return false;
  const elapsed = sinceSend(send.requestedAt, now);
  return elapsed !== null && elapsed < CONFIRM_WINDOW_MS;
}

/** The refetch interval for a screen showing these sends: every 30 s while any is still checking. */
export function checkInterval(sends: SendState[], now: number = Date.now()): number | false {
  return sends.some((send) => stillChecking(send, now)) ? CHECK_EVERY_MS : false;
}

/**
 * The label for an outbound email that has left the draft state, or null for any other status
 * (`draft`, `received`), which keeps its existing wording.
 *
 * "Not confirmed" only when the worker said so (LP-994's prefix); "Still sending" when a Send is
 * still queued or sending once the window has passed.
 */
export function sendStatusLabel(send: SendState, now: number = Date.now()): string | null {
  const { status, errorDetail } = send;
  if ((errorDetail ?? "").startsWith(NOT_CONFIRMED_PREFIX)) return NOT_CONFIRMED_LABEL;
  if (IN_FLIGHT_STATUSES.has(status ?? "")) {
    const elapsed = sinceSend(send.requestedAt, now);
    if (elapsed !== null && elapsed >= CONFIRM_WINDOW_MS) return STILL_SENDING_LABEL;
  }
  switch (status) {
    case "queued":
      return "Queued";
    case "sending":
      return "Sending";
    case "sent":
      return "Sent";
    case "delivered":
      return "Delivered";
    case "failed":
      // LP-994 and LP-995 write most reasons as a whole sentence that already says what happened
      // ("Not sent: …", "Not delivered: …"); "Failed: Not sent: …" would say it twice.
      if (!errorDetail) return "Failed";
      return SAYS_ITSELF.some((start) => errorDetail.startsWith(start))
        ? errorDetail
        : `Failed: ${errorDetail}`;
    default:
      return null;
  }
}

/**
 * The time the labels are read at, moved on when a Send's window ends.
 *
 * A LABEL THAT DEPENDS ON THE CLOCK NEEDS A CLOCK. The last re-check comes back with the same data
 * (still queued), and React Query keeps the same object for unchanged data, so nothing re-renders
 * and "Queued" would stay on screen past the window. This sets one timer for the earliest window end
 * among these sends and re-renders then; with no Send inside its window, it sets none.
 */
export function useSendClock(sends: SendState[]): number {
  const [now, setNow] = useState(() => Date.now());
  const ends = sends
    .filter((send) => stillChecking(send, now))
    .map((send) => Date.parse(send.requestedAt ?? "") + CONFIRM_WINDOW_MS);
  const next = ends.length > 0 ? Math.min(...ends) : null;
  useEffect(() => {
    if (next === null) return;
    const timer = window.setTimeout(() => setNow(Date.now()), Math.max(0, next - Date.now()) + 50);
    return () => window.clearTimeout(timer);
  }, [next]);
  return now;
}
