/**
 * How the admin pages say when something happened (LP-MB-Admin-03, mockups 03 and 12).
 *
 * Today and yesterday are said in words, because that is what an admin scans for; anything older
 * is a date. Empty on an unparseable value rather than "Invalid Date".
 */
import { format, isToday, isYesterday } from "date-fns";

function parse(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const at = new Date(iso);
  return Number.isNaN(at.getTime()) ? null : at;
}

/** "Today 9:12", "Yesterday", "Nov 9"; "Never" for no sign-in at all. */
export function signInLabel(iso: string | null): string {
  if (iso === null) return "Never";
  const at = parse(iso);
  if (!at) return "";
  if (isToday(at)) return `Today ${format(at, "H:mm")}`;
  if (isYesterday(at)) return "Yesterday";
  return format(at, "MMM d");
}

/** An audit row's time: "Today 14:02", "Nov 9 16:41". Always with the time: it is a record. */
export function auditTimeLabel(iso: string): string {
  const at = parse(iso);
  if (!at) return "";
  return isToday(at) ? `Today ${format(at, "H:mm")}` : format(at, "MMM d H:mm");
}

/** "Aug 2": when a person joined. */
export function shortDate(iso: string): string {
  const at = parse(iso);
  return at ? format(at, "MMM d") : "";
}
