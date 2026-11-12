/**
 * Shared auth types (LP-25).
 *
 * Kept dependency-free so the store, the axios client, and the API functions
 * can all import these without creating an import cycle.
 */

/**
 * The authenticated user, matching the backend `UserPublic` schema. This is the
 * only user shape the frontend ever sees — it deliberately carries no
 * `hashed_password` or other sensitive fields.
 */
export interface User {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
  /** The roles the user holds, for display (ADR-440). Never gate on these. */
  roles: string[];
  /** What the user may do, as permission keys (ADR-442). Gate with `useCan`. */
  permissions: string[];
  /** The company's owner: the admin the app will not deactivate or demote. */
  is_owner: boolean;
  company_id: string;
}

/**
 * The body returned by `POST /auth/login` and `POST /auth/refresh`. The
 * refresh token is NOT here — it lives only in the httpOnly cookie.
 */
export interface AuthTokenResponse {
  access_token: string;
  token_type: string;
  user: User;
}
