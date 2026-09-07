/** Secure upload links (LP-815) — mirrors `app/api/upload_links.py`. */

export interface UploadLinkSummary {
  id: string;
  expires_at: string;
  revoked_at: string | null;
  recipient_email: string | null;
  uses: number;
  max_uses: number;
  last_used_at: string | null;
  /** Live: not expired, not revoked, not spent. The server decides; three fields cannot be
   *  recombined on this side without eventually disagreeing with it. */
  is_usable: boolean;
}

/**
 * The mint response, and the ONE place a token ever appears.
 *
 * The row holds a SHA-256 of the token, so this URL cannot be recovered — if it is lost, a new link
 * must be minted. That is the intended property, not a limitation to work around: what the database
 * holds must not be usable to reach a loan file.
 */
export interface MintedUploadLink extends UploadLinkSummary {
  url: string;
}
