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
  /**
   * LP-853 — which language `body` is in, and therefore who wrote it.
   *
   * `"plain"` is a generated draft: templates, placeholders and ADR-401's fingerprints are all
   * untouched by this ticket, so nothing on the backend emits HTML. `"html"` means a processor has
   * written into it, which is why this is also LP-851's `body_edited` — one fact, one place.
   *
   * The editor converts a `plain` body on load and loads an `html` one as-is; the reader renders
   * a `plain` body through `emailBodyToHtml` and shows an `html` one, which the server sanitised
   * against an allowlist on the way in.
   */
  body_format: "plain" | "html";
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
  /** LP-831 review — what a `mailto:` link and a copy need. Nothing here transmits mail, so these
   * are how the message actually reaches anybody. */
  suggested_bcc: string;
  mailto_available: boolean;
  mailto_max_chars: number;
  /**
   * Who to address it to when nobody has yet. Null once a recipient is set.
   *
   * LP-857 — A PARTY'S ADDRESS TOO, not only the borrower's. The old rule suggested nothing on a
   * party draft, on the reasoning that such a draft carries its own address; that holds only when
   * the file had one at creation, and LP-841 deliberately creates the draft either way. The
   * borrower is never suggested on a party draft — that would put a third party's document request
   * in the borrower's inbox.
   */
  suggested_recipient: string | null;
  /**
   * LP-857 — whose draft this is (`borrower`, `title`, `lender`, …), or null.
   *
   * FROM THE SERVER, never derived here. Five parties share `document_request_third_party`, so a
   * client computing the party from `template_key` would file a lender's address under the title
   * company — the same reason the timeline's `party` comes from the server.
   */
  party: string | null;
}
