/** Shared fixtures for the People tests (LP-MB-Admin-03). Not a test file itself. */
import type { AuditPage, Person } from "@/lib/types/users";

export function person(overrides: Partial<Person> = {}): Person {
  return {
    id: "p-elena",
    email: "elena.ruiz@acme.example",
    first_name: "Elena",
    last_name: "Ruiz",
    phone: null,
    title: "Processor",
    nmls_id: null,
    licensed_states: [],
    sees_all_loans: false,
    roles: ["processor"],
    is_owner: false,
    is_active: true,
    last_login_at: null,
    created_at: "2026-08-02T10:00:00Z",
    ...overrides,
  };
}

export const ME = person({
  id: "p-me",
  first_name: "Marcus",
  last_name: "Hill",
  email: "marcus@acme.example",
  roles: ["admin"],
});
export const OWNER = person({
  id: "p-owner",
  first_name: "Priya",
  last_name: "Desai",
  email: "priya@acme.example",
  roles: ["admin", "processor"],
  is_owner: true,
});
export const ELENA = person();
export const AISHA = person({
  id: "p-aisha",
  first_name: "Aisha",
  last_name: "Khan",
  email: "aisha@acme.example",
  is_active: false,
});

export const EMPTY_PAGE: AuditPage = { items: [], next_cursor: null, total: 0 };

/** An axios-shaped refusal, as the server sends it. */
export function refusal(status: number, message: string) {
  return {
    isAxiosError: true,
    response: { status, data: { error: { type: "conflict", message } } },
  };
}
