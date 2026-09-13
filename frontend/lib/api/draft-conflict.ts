/**
 * LP-850's refusal, as the client reads it (LP-851).
 *
 * A request that would create a second open draft for a party is refused with 409 and a payload
 * describing every party the request touched — the ones with a draft already open, and the ones it
 * would simply have created. The whole plan travels so ONE dialog can answer for all of it.
 *
 * NEVER TWO DIALOGS IN SEQUENCE. A processor who has just confirmed five documents and is then
 * asked a second question clicks the primary without reading it, which is exactly how the wrong
 * draft gets chosen. That rule is the reason `would_create` is in this payload at all: a party that
 * needs no decision still has to appear, or a draft to the title company is created without the
 * processor ever learning it exists.
 */
import { isAxiosError } from "axios";

/** What a processor asked for, named as they asked for it. */
export interface ConflictNeed {
  id: string;
  title: string;
}

export interface OpenDraftSummary {
  id: string;
  created_at: string;
  /** What the open draft already asks for. */
  needs: ConflictNeed[];
  /** Whether a processor has written their own words into it — LP-853's `body_format`. */
  body_edited: boolean;
  /**
   * Their own first edited line, for the warning to quote.
   *
   * Null when there is nothing quotable — an edit that only deleted, or one the template happens to
   * contain. The dialog then drops the quotation rather than inventing one.
   */
  edited_excerpt: string | null;
}

export interface DraftDecision {
  party: string;
  open_draft: OpenDraftSummary;
  /** What this request would add to that draft. */
  adding: ConflictNeed[];
}

export interface WouldCreate {
  party: string;
  address: string | null;
  needs: ConflictNeed[];
}

export interface DraftConflict {
  message: string;
  decisions_required: DraftDecision[];
  would_create: WouldCreate[];
}

/** The answer a processor gives, which goes back as `on_conflict`. */
export type ConflictChoice = "append" | "mark_sent_and_new";

/**
 * The conflict inside an error, or null if it is an ordinary failure.
 *
 * NARROW ON PURPOSE. Anything that is not a 409 carrying `decisions_required` is somebody else's
 * error and must still reach the toast — a helper that swallowed a real failure into a dialog
 * nobody could answer would be worse than no dialog at all.
 */
export function draftConflictFrom(error: unknown): DraftConflict | null {
  if (!isAxiosError(error) || error.response?.status !== 409) return null;
  const data = (error.response.data as { error?: { data?: unknown } } | undefined)?.error?.data;
  if (typeof data !== "object" || data === null) return null;
  const conflict = data as Partial<DraftConflict>;
  if (!Array.isArray(conflict.decisions_required) || conflict.decisions_required.length === 0) {
    return null;
  }
  return {
    message: typeof conflict.message === "string" ? conflict.message : "",
    decisions_required: conflict.decisions_required,
    would_create: Array.isArray(conflict.would_create) ? conflict.would_create : [],
  };
}

/**
 * The party as a processor says it, not as the catalog keys it.
 *
 * DERIVED FROM THE SAME VOCABULARY the timeline uses, because two spellings of "title company" on
 * two screens is how a processor stops believing either. An unknown value renders as itself rather
 * than as nothing — a party we have no word for is still a party they must be told about.
 */
export const PARTY_NOUN: Record<string, string> = {
  borrower: "borrower",
  employer: "employer",
  lender: "lender",
  title: "title company",
  cpa: "accountant",
  agent: "agent",
  insurer: "insurer",
};

export function partyNoun(party: string): string {
  return PARTY_NOUN[party] ?? party;
}
