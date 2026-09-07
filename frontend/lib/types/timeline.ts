/** The communication timeline (LP-812) — mirrors `app/api/timeline.py`. */

/** What a row IS. The server decides, so the client never re-derives it. */
export type TimelineKind = "message" | "activity";

/** Spec 4.3's filter pills. Defined by the SERVER — see `services/timeline.py`. */
export type TimelineFilter = "all" | "sent" | "received" | "drafts" | "activity";

export interface TimelineEntry {
  id: string;
  kind: TimelineKind;
  /** When it belongs. A sent message sits at `sent_at`, not at composition. */
  at: string;
  summary: string;
  direction: "inbound" | "outbound" | null;
  status: string | null;
  subject: string | null;
  /** Sender for inbound, recipient for outbound. Null on an activity. */
  counterparty: string | null;
  actor_user_id: string | null;
  /** Filenames on an inbound message. Sender-written text — rendered, never used to build a URL. */
  attachments: string[];
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
}
