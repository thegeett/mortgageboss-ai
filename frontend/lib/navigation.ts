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
import {
  Building2,
  FileText,
  FolderOpen,
  LayoutDashboard,
  MessageSquare,
  Package,
  ScrollText,
  ShieldCheck,
  SlidersHorizontal,
} from "lucide-react";

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

/**
 * The context column's contents (LP-UI-008).
 *
 * The 52px rail is the same everywhere; the 216px column beside it depends on
 * where you are. A processor inside a file wants that file's sections, not the
 * app's top-level destinations — those are already one click away on the rail.
 */
export interface ContextSection {
  title: string;
  items: { label: string; href: string; icon: LucideIcon }[];
}

/** File sections, relative to a file's base route. */
export function fileSections(fileId: string): ContextSection {
  const base = `/loan-files/${fileId}`;
  return {
    title: "File",
    items: [
      { label: "Overview", href: base, icon: LayoutDashboard },
      { label: "Documents", href: `${base}/documents`, icon: FileText },
      { label: "Verification", href: `${base}/verification`, icon: ShieldCheck },
      // Needs is deliberately absent. "Needs becomes its own route" is one of the
      // standing decisions, but `/loan-files/[id]/needs` does not exist yet —
      // listing it here would ship a link to a 404. It goes in with the route.
      { label: "Communication", href: `${base}/communication`, icon: MessageSquare },
      { label: "Conditions", href: `${base}/conditions`, icon: ScrollText },
      { label: "Lender package", href: `${base}/lender-package`, icon: Package },
    ],
  };
}

const ADMIN_SECTION: ContextSection = {
  title: "Administration",
  items: [
    { label: "Overview", href: "/admin", icon: ShieldCheck },
    { label: "Lenders", href: "/admin/lenders", icon: Building2 },
    { label: "Validation", href: "/admin/validation", icon: SlidersHorizontal },
  ],
};

const PIPELINE_SECTION: ContextSection = {
  title: "Pipeline",
  items: [
    { label: "Dashboard", href: "/dashboard", icon: LayoutDashboard },
    { label: "All loan files", href: "/loan-files", icon: FolderOpen },
  ],
};

/** Extract a loan-file id from a `/loan-files/<id>` path, or null. */
export function loanFileIdFromPath(pathname: string): string | null {
  const match = pathname.match(/^\/loan-files\/([^/]+)/);
  const id = match?.[1];
  // `/loan-files/new` is a page, not a file.
  return id && id !== "new" ? id : null;
}

/** What the context column shows for `pathname`. `null` = show nothing. */
export function contextSection(pathname: string): ContextSection | null {
  const fileId = loanFileIdFromPath(pathname);
  if (fileId) return fileSections(fileId);
  if (pathname.startsWith("/admin")) return ADMIN_SECTION;
  if (pathname.startsWith("/dashboard") || pathname.startsWith("/loan-files")) {
    return PIPELINE_SECTION;
  }
  return null;
}
