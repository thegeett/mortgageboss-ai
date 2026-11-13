/** Staff invitations as the API returns them (LP-MB-Admin-04). */
import type { Role } from "@/lib/types/users";

/** One pending invitation. Never the token. */
export interface Invite {
  id: string;
  email: string;
  roles: Role[];
  invited_by_name: string | null;
  created_at: string;
  last_sent_at: string;
  expires_at: string;
  send_count: number;
  /** Past its expiry: the link no longer works; Resend issues a new one. */
  expired: boolean;
}

/** A create or resend. `accept_url` only when the server has no mail transport. */
export interface InviteIssued {
  invite: Invite;
  accept_url: string | null;
}

/** What the person holding the link sees. */
export interface InviteLookup {
  company_name: string;
  email: string;
  roles: Role[];
  invited_by_name: string | null;
}
