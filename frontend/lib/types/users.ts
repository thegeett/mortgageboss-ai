/** People and the audit log as the admin API returns them (LP-MB-Admin-03). */

export type Role = "admin" | "loan_officer" | "processor";

/** Every role, in the order the People sheet lists them. */
export const ROLES: readonly Role[] = ["admin", "loan_officer", "processor"];

export const ROLE_LABEL: Record<Role, string> = {
  admin: "Admin",
  loan_officer: "Loan officer",
  processor: "Processor",
};

/** One person on the People page (backend `UserAdminView`). */
export interface Person {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
  phone: string | null;
  title: string | null;
  nmls_id: string | null;
  licensed_states: string[];
  sees_all_loans: boolean;
  roles: Role[];
  is_owner: boolean;
  is_active: boolean;
  last_login_at: string | null;
  created_at: string;
}

/** `PATCH /users/{id}`: only the fields that changed. */
export type PersonDetailsUpdate = Partial<
  Pick<
    Person,
    | "first_name"
    | "last_name"
    | "phone"
    | "title"
    | "nmls_id"
    | "licensed_states"
    | "sees_all_loans"
  >
>;

/** One field's before and after, as the server's `field_changes` writes it. */
export interface AuditChange {
  field: string;
  from: unknown;
  to: unknown;
}

export interface AuditEntry {
  id: string;
  created_at: string;
  /** Null: the system (a migration or a MortgageBoss script). */
  actor: { id: string; name: string } | null;
  action: string;
  target_type: string;
  target_id: string | null;
  target_name: string | null;
  summary: string;
  detail: { changes?: AuditChange[] } & Record<string, unknown>;
}

export interface AuditPage {
  items: AuditEntry[];
  next_cursor: string | null;
  total: number;
}

export interface AuditFilters {
  target_type?: string;
  target_id?: string;
  actor_user_id?: string;
  since?: string;
}
