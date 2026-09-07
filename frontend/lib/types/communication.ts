/** Outbound draft types (LP-811b) — mirrors `app/schemas/communication.py`. */

export interface OutboundDraft {
  id: string;
  subject: string;
  body: string;
  reply_to: string;
  suggested_bcc: string;
  /**
   * Whether a `mailto:` link can carry this message intact. Computed SERVER-SIDE, deliberately:
   * `mailto:` does not fail when it is too long, it opens a compose window containing half an
   * email, and two places working out the same threshold is two places to disagree about it.
   */
  mailto_available: boolean;
  mailto_max_chars: number;
  needs_item_count: number;
  /** The primary borrower's email, or null when the file has none (LP-823). */
  suggested_recipient: string | null;
}

export interface SentCommunication {
  id: string;
  status: string;
  sent_at: string | null;
  needs_items_requested: number;
}
