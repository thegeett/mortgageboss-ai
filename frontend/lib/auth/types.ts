/**
 * Shared auth types (LP-25).
 *
 * Kept dependency-free so the store, the axios client, and the API functions
 * can all import these without creating an import cycle.
 */

/** User roles, mirroring the backend `UserRole` enum. */
export type UserRole = "processor" | "admin";

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
  role: UserRole;
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
