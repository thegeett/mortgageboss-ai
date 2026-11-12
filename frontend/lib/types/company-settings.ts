/** The company's three settings, matching the backend `CompanySettingsPublic` (LP-MB-Admin-02). */
export interface CompanySettings {
  processors_can_create_loans: boolean;
  processors_can_invite_borrowers: boolean;
  restrict_loans_to_team: boolean;
}

/** `PATCH /company/settings`: any subset; an omitted setting is left as it is. */
export type CompanySettingsUpdate = Partial<CompanySettings>;
