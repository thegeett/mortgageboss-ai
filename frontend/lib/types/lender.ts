/** A lender as returned by `GET /lenders` (LP-32) — for the intake dropdown. */
export interface LenderSummary {
  id: string;
  name: string;
  supported_programs: string[];
}

/** What an admin configures. Wider than the picker's view — see `LenderDetail` in the API. */
export interface LenderDetail {
  id: string;
  name: string;
  slug: string;
  supported_programs: string[];
  contact_email: string | null;
  contact_phone: string | null;
  portal_url: string | null;
  notes: string | null;
  is_active: boolean;
}

/** What a lender contact does. `underwriter` is the one the product is built around. */
export type LenderContactRole = "underwriter" | "account_executive" | "closer" | "other";

/** A named person at a lender (LP-813) — who a file is actually assigned to. */
export interface LenderContact {
  id: string;
  lender_id: string;
  name: string;
  email: string | null;
  phone: string | null;
  role: LenderContactRole;
  notes: string | null;
  is_active: boolean;
}
