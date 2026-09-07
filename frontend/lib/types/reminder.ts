/** Reminder suggestions (LP-814) — mirrors `app/api/reminders.py`. */

/** Which rule produced a suggestion. Part of its identity: snoozing one does not snooze another. */
export type ReminderKind = "needs_item_pending" | "no_reply" | "file_untouched";

export interface Suggestion {
  loan_file_id: string;
  display_id: string;
  kind: ReminderKind;
  /** The need or message it is about; null for a rule about the file itself. */
  subject_id: string | null;
  /** Written by us — never a borrower's words. Safe to render. */
  summary: string;
  /** How long the thing has been true, in whole days. */
  days: number;
  since: string;
}
