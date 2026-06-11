/**
 * App-shell navigation config (LP-27).
 *
 * One source of truth for the sidebar (desktop) and the mobile nav menu. Adding
 * a destination as Epic 4+ ships pages is a one-line edit here. Items may be
 * role-gated via `requiredRole`; `visibleNavItems(role)` does the filtering.
 *
 * Role gating here is **UX only** — it hides chrome the user can't use. The
 * backend is the real authorization boundary (LP-24 `require_role`).
 */
import type { UserRole } from "@/lib/auth/types";
import type { LucideIcon } from "lucide-react";
import { FolderOpen, LayoutDashboard, ShieldCheck } from "lucide-react";

export interface NavItem {
  label: string;
  href: string;
  icon: LucideIcon;
  /** If set, the item is only shown to users with this role. */
  requiredRole?: UserRole;
}

export const NAV_ITEMS: NavItem[] = [
  { label: "Dashboard", href: "/dashboard", icon: LayoutDashboard },
  { label: "Loan Files", href: "/loan-files", icon: FolderOpen },
  { label: "Administration", href: "/admin", icon: ShieldCheck, requiredRole: "admin" },
];

/** The nav items a user with `role` may see (undefined role → only public items). */
export function visibleNavItems(role: UserRole | undefined): NavItem[] {
  return NAV_ITEMS.filter((item) => item.requiredRole === undefined || item.requiredRole === role);
}

/** True if `pathname` is within `href` (exact, or a nested child route). */
export function isActivePath(pathname: string, href: string): boolean {
  return pathname === href || pathname.startsWith(`${href}/`);
}
