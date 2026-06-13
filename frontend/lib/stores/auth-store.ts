/**
 * In-memory auth store (LP-25).
 *
 * Holds the access token and the current user IN MEMORY only — never
 * localStorage, sessionStorage, or a JS-set cookie. This is the client half of
 * the hybrid transport: the access token is deliberately volatile and vanishes
 * on a full page reload, at which point AuthProvider's silent refresh
 * re-establishes the session from the httpOnly refresh cookie.
 *
 * `isInitializing` is true until that first silent-refresh attempt settles, so
 * the UI can show a loading state instead of flashing the login screen or
 * protected content before we know whether the user is signed in.
 */
import type { User } from "@/lib/auth/types";
import { create } from "zustand";

interface AuthState {
  accessToken: string | null;
  user: User | null;
  /** True until the on-load silent refresh resolves (success or failure). */
  isInitializing: boolean;
  setAuth: (auth: { accessToken: string; user: User }) => void;
  clearAuth: () => void;
  finishInitializing: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  accessToken: null,
  user: null,
  isInitializing: true,
  setAuth: ({ accessToken, user }) => set({ accessToken, user }),
  clearAuth: () => set({ accessToken: null, user: null }),
  finishInitializing: () => set({ isInitializing: false }),
}));

/**
 * Derived authentication flag: a user is authenticated when we hold both an
 * access token and a user record. Plain function so it works both inside React
 * (pass to {@link useAuthStore}) and outside it (interceptors via `getState`).
 */
export const selectIsAuthenticated = (state: AuthState): boolean =>
  state.accessToken !== null && state.user !== null;

/** Hook selector for components that only need the boolean. */
export const useIsAuthenticated = (): boolean => useAuthStore(selectIsAuthenticated);
