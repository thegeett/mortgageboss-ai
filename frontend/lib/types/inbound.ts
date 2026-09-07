/** Inbound triage types (LP-806/LP-807) — mirrors `app/schemas/inbound.py`. */

/** Whether an attachment may be treated as a document. `pending` is NOT a pass. */
export type SafetyState = "pending" | "safe" | "quarantined" | "unsupported";

/** What a processor did with it. */
export type Disposition = "pending" | "accepted" | "correspondence" | "rejected" | "duplicate";

/** Where a message got to. `unrouted` means nobody owns it yet. */
export type RoutingState = "pending" | "routed" | "unrouted" | "rejected";

export interface InboundAttachment {
  id: string;
  /**
   * What the sender called it — attacker-controlled text, and NULL on an unclaimed message.
   *
   * Returned because a processor deciding whether to accept a file has to see what it was called,
   * and the normalised form has had exactly that removed. It is rendered as text and never as
   * markup, never used to build a URL, and never put in a `title` or an `href`.
   */
  filename_original: string | null;
  filename_normalized: string | null;
  declared_content_type: string | null;
  sniffed_content_type: string | null;
  size_bytes: number;
  safety_state: SafetyState;
  /** Why it was refused, in words a processor can act on. Written by us, safe to show. */
  safety_reason: string | null;
  disposition: Disposition;
  /** How deep inside forwarded messages this was found. 0 is the outer message. */
  nesting_depth: number;
}

export interface InboundMessage {
  id: string;
  loan_file_id: string | null;
  routing_state: RoutingState;
  routing_signal: string | null;
  routing_confidence: number | null;
  is_dsn: boolean;
  is_auto_reply: boolean;
  /**
   * NULL ON AN UNCLAIMED MESSAGE, and that is a state to render, not missing data.
   *
   * An unrouted message has no company, so the queue returns it to every company that asks — which
   * is why nothing the sender wrote travels with it until somebody claims it.
   */
  from_address: string | null;
  subject: string | null;
  received_at: string | null;
  /** SES's verdicts, verbatim. `GRAY` is not `PASS`. */
  auth_verdicts: Record<string, string>;
  attachments: InboundAttachment[];
}

export interface AcceptResult {
  document_id: string | null;
  disposition: Disposition;
  possible_duplicate: boolean;
}
