/**
 * "Since you last looked" (LP-852).
 *
 * NOT AN UNREAD BADGE, and the distinction is the ticket's. Nothing is received in this version, so
 * "unread" would be a claim about somebody ELSE's behaviour — whether a borrower opened a message.
 * This is a claim about THIS processor: which drafts appeared since they last had this page open.
 *
 * PER BROWSER, VIA `localStorage`, and that is honestly less than "per processor". A server-side
 * per-user timestamp would be the real thing and is a schema change; this is the cheap version that
 * is right for the common case — one person, one machine — and degrades to "nothing is new" on a
 * second machine rather than to a wrong claim. It is a dot, not a number, for exactly that reason.
 *
 * EVERY ACCESS IS GUARDED. `localStorage` throws outright in a few privacy configurations and does
 * not exist during a server render, and a drafts list that failed to render because a decoration
 * could not be stored would be a worse outcome than no decoration.
 */

const KEY = (fileId: string) => `mbai:comm-last-seen:${fileId}`;

/** When this processor last had this file's communication page open, or null. */
export function readLastSeen(fileId: string): string | null {
  try {
    return window.localStorage.getItem(KEY(fileId));
  } catch {
    return null;
  }
}

/** Record that they are looking at it now. */
export function writeLastSeen(fileId: string, at: string): void {
  try {
    window.localStorage.setItem(KEY(fileId), at);
  } catch {
    // A dot is a convenience. Failing to store it must not fail the page.
  }
}

/**
 * Whether this draft appeared since `lastSeen`.
 *
 * NO `lastSeen` MEANS NOTHING IS NEW, not that everything is. A processor opening the page for the
 * first time on a file with ten drafts would otherwise meet ten dots, which says "all of this is
 * new to you" — true, useless, and it teaches them the dot means nothing.
 */
export function isNewSince(createdAt: string | null, lastSeen: string | null): boolean {
  if (!createdAt || !lastSeen) return false;
  const created = new Date(createdAt).getTime();
  const seen = new Date(lastSeen).getTime();
  if (Number.isNaN(created) || Number.isNaN(seen)) return false;
  return created > seen;
}
