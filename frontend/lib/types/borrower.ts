/** Borrower detail (LP-34), mirroring the backend `BorrowerResponse` from the
 * `/loan-files/{id}/borrowers` endpoint — `masked_ssn` only, never raw SSN. */

export type MaritalStatus = "married" | "unmarried" | "separated";

export interface BorrowerDetail {
  id: string;
  first_name: string;
  last_name: string;
  middle_name: string | null;
  masked_ssn: string | null;
  date_of_birth: string | null;
  email: string | null;
  phone: string | null;
  marital_status: MaritalStatus | null;
  is_primary: boolean;
  borrower_position: number;
}
