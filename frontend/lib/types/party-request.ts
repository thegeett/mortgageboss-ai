/** Non-borrower request paths (LP-820) — mirrors `app/api/party_requests.py`. */

/** Who holds a document. `processor` never appears here: they order it and are asked nothing. */
export type ResponsibleParty =
  | "borrower"
  | "lender"
  | "title"
  | "employer"
  | "cpa"
  | "agent"
  | "insurer";

export interface PartyNeed {
  id: string;
  title: string;
}

export interface PartyRequest {
  party: ResponsibleParty;
  role: string;
  /** Where the request would go, or null — which is the state this screen exists to surface. */
  address: string | null;
  name: string | null;
  /**
   * False when nothing on this file can reach them.
   *
   * THE UNREACHABLE ROWS ARE THE POINT. A screen showing only what it can send presents a file with
   * five outstanding title documents as having nothing to do.
   */
  reachable: boolean;
  needs: PartyNeed[];
}
