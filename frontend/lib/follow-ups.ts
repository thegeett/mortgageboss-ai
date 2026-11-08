/**
 * LP-1014 — what a follow-up's state means on screen, and its dates. No React, no requests.
 *
 * THE STATE IS DERIVED ONCE, here, and every place that shows a follow-up (the bar on the email,
 * the pill on the list row, the Follow-ups list) reads it from this function. "No reply" is not a
 * server status: it is `on` with every automatic reminder spent.
 */
import type { FollowUp } from "@/lib/types/communication";

export type FollowUpState =
  | "on"
  | "paused"
  | "no_reply"
  | "finished"
  | "stopped_sender_inactive"
  | "stopped_failed"
  | "stopped"
  | "off";

/** `emailFailed`: the original email itself failed, so it can never be started again (the server's
 * Start refuses it). */
export function followUpState(
  followUp: FollowUp,
  senderActive = true,
  emailFailed = false,
): FollowUpState {
  switch (followUp.status) {
    case "on":
      if (followUp.auto_sent < followUp.max_auto) return "on";
      // LP-1014 fix (11-08) — reminders spent but nothing missing: everything arrived. The job
      // never picks a spent follow-up again, so the server leaves it `on`; this is not "No reply".
      // A general email waits for ["a reply"], never empty, so it stays "No reply".
      return followUp.waiting_for.length === 0 ? "finished" : "no_reply";
    case "paused":
      return "paused";
    case "finished":
      return "finished";
    case "stopped":
      if (emailFailed) return "stopped_failed";
      return senderActive ? "stopped" : "stopped_sender_inactive";
    default:
      return "off";
  }
}

export type PillTone = "success" | "warning" | "danger" | "neutral";

/** The role classes for each tone; no palette names (CLAUDE.md, colour is two layers). */
export const PILL_CLASSES: Record<PillTone, string> = {
  success: "border-success/40 bg-success/10 text-success",
  warning: "border-warning/50 bg-warning/10 text-warning",
  danger: "border-danger/40 bg-danger/10 text-danger",
  neutral: "border-border bg-muted text-muted-foreground",
};

/** The pill on a list row: `Follow-up · Mon`, `Paused`, `No reply`, `Stopped`, `Finished`. Null
 * for `off`, which has no pill. */
export function followUpPill(
  followUp: FollowUp,
  senderActive = true,
): { label: string; tone: PillTone } | null {
  const state = followUpState(followUp, senderActive);
  switch (state) {
    case "on": {
      const day = followUp.next_reminder_at
        ? weekdayIn(followUp.next_reminder_at, followUp.tz)
        : null;
      return { label: day ? `Follow-up · ${day}` : "Follow-up", tone: "success" };
    }
    case "paused":
      return { label: "Paused", tone: "warning" };
    case "no_reply":
      return { label: "No reply", tone: "danger" };
    case "finished":
      return { label: "Finished", tone: "neutral" };
    case "stopped":
    case "stopped_sender_inactive":
    case "stopped_failed":
      return { label: "Stopped", tone: "neutral" };
    default:
      return null;
  }
}

/** The browser's IANA time zone, e.g. `America/New_York`. */
export function browserTimeZone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone;
}

/** `HH:MM` of `now` on the browser's clock: the time picker's default. */
export function currentTime(now: Date = new Date()): string {
  return `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`;
}

function weekdayIn(iso: string, tz: string | null): string {
  return new Intl.DateTimeFormat("en-US", {
    weekday: "short",
    ...(tz ? { timeZone: tz } : {}),
  }).format(new Date(iso));
}

/** `Mon, Nov 9 at 9:30 AM`, read in `tz` (the follow-up's own zone), or the browser's. */
export function formatWhen(when: Date | string, tz?: string | null): string {
  const date = typeof when === "string" ? new Date(when) : when;
  const zone = tz ? { timeZone: tz } : {};
  const day = new Intl.DateTimeFormat("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    ...zone,
  }).format(date);
  const time = new Intl.DateTimeFormat("en-US", {
    hour: "numeric",
    minute: "2-digit",
    ...zone,
  }).format(date);
  return `${day} at ${time}`;
}

/**
 * The first reminder for an email sent `now`: `days` later on the browser's calendar, a Saturday or
 * Sunday moved to Monday, at `time`. The server's rule (`due_moment`) with the clock at the Send
 * and the zone the browser's — which is the zone the Send carries.
 */
export function firstReminderAt(now: Date, days: number, time: string): Date {
  const [hours, minutes] = time.split(":").map(Number);
  const due = new Date(now.getFullYear(), now.getMonth(), now.getDate() + days);
  const weekday = due.getDay(); // 0 Sunday, 6 Saturday
  if (weekday === 6) due.setDate(due.getDate() + 2);
  if (weekday === 0) due.setDate(due.getDate() + 1);
  due.setHours(hours ?? 0, minutes ?? 0, 0, 0);
  return due;
}

/** `1 of 2 sent`. */
export function sentCount(followUp: FollowUp): string {
  return `${followUp.auto_sent} of ${followUp.max_auto} sent`;
}
