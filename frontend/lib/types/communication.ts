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

/** One file on an inbound message, and what became of it (LP-825). */
export interface MessageAttachment {
  name: string;
  disposition: string;
}

/**
 * One message in full (LP-829).
 *
 * `body` is here and is the point: before this, a sent message's words were readable nowhere in the
 * product. For an OPEN DRAFT the server has already resolved LP-823's deferred placeholders; for a
 * sent message they were resolved when it went out; for an inbound message the body is exactly what
 * the borrower wrote, placeholders and all.
 */
export interface MessageDetail {
  id: string;
  direction: "inbound" | "outbound";
  status: string;
  subject: string | null;
  body: string;
  /** Sender for inbound, recipient for outbound. Null on a draft nobody has addressed yet. */
  counterparty: string | null;
  template_key: string | null;
  template_version: string | null;
  created_at: string;
  sent_at: string | null;
  read_at: string | null;
  is_important: boolean;
  /** Why a send failed, in the provider's own words. Null on everything else. */
  error_detail: string | null;
  /** Outbound: what this message asks for. Empty on inbound. */
  documents: string[];
  /** Inbound: what arrived, and what became of each. Empty on outbound. */
  attachments: MessageAttachment[];
  is_open_draft: boolean;
  /**
   * LP-831 — whether the modal offers an editor and a send.
   *
   * WIDER THAN `is_open_draft`, which is the BORROWER's draft specifically. A party request is a
   * draft under its own template key, and `get_open_draft` filtering on the borrower's is the
   * reason no screen could send one — while `send_draft` has never cared which template rendered it.
   */
  is_editable: boolean;
  /** Who to address it to when nobody has yet. Null once a recipient is set. */
  suggested_recipient: string | null;
}
