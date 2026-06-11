/**
 * Auth API functions (LP-25).
 *
 * Thin, typed wrappers over the backend auth endpoints. They use the shared
 * {@link apiClient} (so the Bearer/refresh interceptors apply) and keep the
 * in-memory store in sync. `refreshSession`/`logout` rely on `withCredentials`
 * so the browser sends the httpOnly refresh cookie.
 */
import {
  AUTH_LOGIN_PATH,
  AUTH_LOGOUT_PATH,
  AUTH_ME_PATH,
  apiClient,
  refreshAccessToken,
} from "@/lib/api/client";
import type { AuthTokenResponse, User } from "@/lib/auth/types";
import { useAuthStore } from "@/lib/stores/auth-store";

/**
 * Log in with email + password. On success the access token + user are stored
 * in memory and the refresh cookie is set by the backend. The caller surfaces
 * the backend's generic error on failure (never reveal whether the email exists).
 */
export async function login(email: string, password: string): Promise<User> {
  const response = await apiClient.post<AuthTokenResponse>(AUTH_LOGIN_PATH, {
    email,
    password,
  });
  const { access_token, user } = response.data;
  useAuthStore.getState().setAuth({ accessToken: access_token, user });
  return user;
}

/**
 * Log out: clear the refresh cookie server-side, then drop the in-memory
 * session. The local state is cleared even if the network call fails, so the
 * client never appears "stuck" signed in.
 */
export async function logout(): Promise<void> {
  try {
    await apiClient.post(AUTH_LOGOUT_PATH);
  } finally {
    useAuthStore.getState().clearAuth();
  }
}

/**
 * Silently re-establish the session from the httpOnly refresh cookie (used on
 * app load). Delegates to the de-duplicated {@link refreshAccessToken}, which
 * updates the store; throws if there is no valid refresh cookie.
 */
export async function refreshSession(): Promise<void> {
  await refreshAccessToken();
}

/** Fetch the current user from the protected `/auth/me` endpoint. */
export async function fetchCurrentUser(): Promise<User> {
  const response = await apiClient.get<User>(AUTH_ME_PATH);
  return response.data;
}
