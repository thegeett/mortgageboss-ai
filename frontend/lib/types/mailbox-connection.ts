/** Route B mailbox connections (LP-808) — mirrors `app/api/mailbox_connections.py`. */

/** Health. Separate from verification — a connection can be healthy and unfinished. */
export type ConnectionStatus = "connected" | "degraded" | "needs_reauthorization" | "revoked";

/** Whether the routing rule has ever been seen to work. Flipped automatically, never by a button. */
export type ConnectionVerification = "not_verified" | "awaiting_first_message" | "verified";

export interface MailboxConnection {
  id: string;
  kind: string;
  provider: string | null;
  /**
   * `co-<token>@…` — the address an admin routes mail to.
   *
   * THE ADDRESS CONTAINS THE TOKEN, so this is a bearer capability, not a label (ADR-397). Anyone
   * who can send to it gets mail into this company's triage queue.
   */
  address: string;
  source_address: string | null;
  status: ConnectionStatus;
  verification: ConnectionVerification;
  last_success_at: string | null;
  consecutive_failures: number;
  /** Verified, not revoked, and quiet for `stale_after_days`. The SERVER decides — three fields
   *  recombined here would eventually disagree with it. */
  is_stale: boolean;
  stale_after_days: number;
}

export interface ConnectionSteps {
  provider: string;
  steps: string[];
}
