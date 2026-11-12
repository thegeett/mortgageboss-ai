/**
 * Permission checks for the UI (LP-MB-Admin-02, ADR-442).
 *
 * The server resolves what a user may do and sends it as `user.permissions`; the UI asks
 * "may this user do X?" by the same key the API checks. It never compares roles. This is
 * UX only — it hides what the user cannot use. The backend is the boundary.
 */
import { useAuthStore } from "@/lib/stores/auth-store";

/**
 * True if the signed-in user holds `permission` (false while signed out).
 *
 * `permissions?.` although the type says it is always there: a backend from before LP-MB-Admin-02
 * sends a user without it (a frontend deployed first meets one), and a missing list must read as
 * "holds nothing", not crash every page that asks.
 */
export function useCan(permission: string): boolean {
  return useAuthStore((state) => state.user?.permissions?.includes(permission) ?? false);
}
