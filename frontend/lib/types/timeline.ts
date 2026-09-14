/** The communication timeline (LP-812) — mirrors `app/api/timeline.py`. */

/** What a row IS. The server decides, so the client never re-derives it. */
/** LP-825 — one member. The timeline carries messages; the file's other history is on Recent
 * activity, where it always belonged. Kept as a union so LP-829 can add to it. */
export type TimelineKind = "message";

/** Spec 4.3's filter pills. Defined by the SERVER — see `services/timeline.py`. */
/** LP-825 — no "activity" pill: it could only match an activity row, and there are none. */
export type TimelineFilter = "all" | "sent" | "received" | "drafts";

/** One file on an inbound message, and what became of it. */
export interface TimelineAttachment {
  name: string;
  /** `pending` | `accepted` | `correspondence` | `rejected`. */
  disposition: string;
}

export interface TimelineEntry {
  id: string;
  kind: TimelineKind;
  /** When it belongs. A sent message sits at `sent_at`, not at composition. */
  at: string;
  summary: string;
  direction: "inbound" | "outbound" | null;
  status: string | null;
  subject: string | null;
  /** Sender for inbound, recipient for outbound. */
  counterparty: string | null;
  actor_user_id: string | null;
  /** Attachments on an inbound message, each with what became of it (LP-825 review). The name is
   * sender-written text — rendered, never used to build a URL. The disposition is ours. */
  attachments: TimelineAttachment[];
  /** Flagged by a processor (LP-818). Never computed and never suggested by a model. */
  is_important: boolean;
  /** An arrived message nobody has opened. Always false for outbound — we wrote those. */
  unread: boolean;
  /**
   * LP-841 — whose bucket this belongs in: `borrower`, `lender`, `title`, `employer`, `cpa`,
   * `agent`, `insurer`, or null.
   *
   * FROM THE SERVER, not derived here. An outbound message's party is decided by the template key
   * its draft was filed under, and a second definition of that on the client is how a lender draft
   * comes to exist with an empty Lender tab in front of it. Null is a real answer, not a gap: an
   * inbound message from an address nobody on the file recognises belongs in no party's thread.
   */
  party: string | null;
  /**
   * LP-852 — what the draft asks for, so a row says what is inside without being opened.
   *
   * Four rows reading "A document request is being prepared", identical but for a timestamp, is the
   * screenshot that started that ticket. Names rather than a count alone: a count says how much is
   * in an email and not whether it is the one a processor is looking for.
   */
  documents: string[];
  /** LP-852 — who wrote it, for the attributed status. "Marked sent by Priya", never "Sent". */
  actor_name: string | null;
  /** LP-852 — `Draft · edited · 2m`. LP-853's `body_format` is where this is stored. */
  body_edited: boolean;
  /**
   * LP-859 §3 — nothing has been written into this draft: no template, no recipient, no subject,
   * no body, nothing linked. The row reads `New message` / `Nothing written yet`.
   *
   * FROM THE SERVER, for the reason `party` is. `email_reply.draft_row_is_blank` decides it — the
   * same predicate the hard delete uses — and one of the fields it reads (`template_key`) is not on
   * this entry at all, so a client-side version would be a DIFFERENT rule wearing the same name.
   */
  nothing_written: boolean;
  /**
   * LP-852 — when the draft came into existence, which is NOT `at`.
   *
   * `at` is `sent_at or created_at` so the list orders by when the borrower heard from us; the
   * "since you last looked" dot is about when the draft was written, and for a sent message those
   * are different days.
   */
  created_at: string | null;
  detail: Record<string, unknown>;
}

export interface Timeline {
  entries: TimelineEntry[];
  /**
   * True when the file's history is longer than this response.
   *
   * There is no pagination yet, so the cap drops the OLDEST entries — a page that looks complete
   * and is not. A processor hunting the message that started a thread would find a whole-looking
   * timeline without it. Render this as "older entries not shown" rather than letting the absence
   * imply there are none.
   */
  truncated: boolean;
  /**
   * The file's inbox address, for telling a borrower where to send documents.
   *
   * A BEARER CAPABILITY (ADR-397), not a label: anyone holding it can post documents into this file.
   * It is on this screen because spec 4.3 asks for it here — a processor noticing nothing has
   * arrived is already looking at the timeline.
   */
  inbox_address: string;
  /** Arrived messages nobody has opened, counted over the WHOLE file — not over `entries`, or the
   *  badge would shrink when somebody clicked a filter pill. */
  unread_count: number;
}
