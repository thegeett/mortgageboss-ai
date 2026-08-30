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
  /**
   * Extra path prefixes this destination REPRESENTS without linking to.
   *
   * LP-UI-011 removed the "Loan Files" rail item because `/loan-files` now
   * redirects to the dashboard — correctly, since two destinations meaning one
   * screen is the duplication it set out to remove. But `/loan-files/<id>` is
   * still a real place, and it was the only thing marking the rail while a
   * processor was in a file. Without this the rail shows NOTHING current on the
   * screen the product is mostly used on, and the header falls back to the
   * wordmark. The dashboard is the loan-file list (ADR-390), so a file is inside
   * its territory; saying so is what keeps the rail honest.
   */
  owns?: string[];
}

export const NAV_ITEMS: NavItem[] = [
  // "Loan Files" is deliberately absent (LP-UI-011). It pointed at a stub that
  // said the real thing arrived in Epic 4; Epic 4 arrived, and the dashboard is
  // that list. Two rail destinations meaning one screen is the duplication this
  // ticket removes — `/loan-files` now redirects here.
  { label: "Dashboard", href: "/dashboard", icon: LayoutDashboard, owns: ["/loan-files"] },
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

/** Whether a rail destination represents `pathname` — its own route or one it owns. */
export function isNavItemActive(pathname: string, item: NavItem): boolean {
  if (isActivePath(pathname, item.href)) return true;
  return (item.owns ?? []).some((prefix) => isActivePath(pathname, prefix));
}

/**
 * Which of `hrefs` is the CURRENT one for `pathname` — the longest match, or null.
 *
 * `isActivePath` alone is wrong for a list whose first item is the section index.
 * "Overview" is `/loan-files/<id>` and "Documents" is `/loan-files/<id>/documents`,
 * so on the documents page `isActivePath` is true for BOTH and the column marked
 * two links `aria-current="page"` at once — a screen reader announces two current
 * pages, and two rows read as selected. Administration has the same shape
 * (`/admin` beside `/admin/lenders`). The longest match is the specific one.
 */
export function activeItemHref(pathname: string, hrefs: string[]): string | null {
  let best: string | null = null;
  for (const href of hrefs) {
    if (isActivePath(pathname, href) && (best === null || href.length > best.length)) {
      best = href;
    }
  }
  return best;
}

/** Extract a loan-file id from a `/loan-files/<id>` path, or null. */
export function loanFileIdFromPath(pathname: string): string | null {
  const match = pathname.match(/^\/loan-files\/([^/]+)/);
  const id = match?.[1];
  // `/loan-files/new` is a page, not a file.
  return id && id !== "new" ? id : null;
}

/**
 * The tab segment for a path inside a file — "documents", "verification", … —
 * or null on the file's index (and on any path that is not inside a file).
 *
 * `pathname.endsWith("/documents")` answered the same question by matching the
 * END of the whole path, which is true for any route that happens to finish with
 * the same word however deeply nested, and false for a trailing slash. This
 * anchors to the file's own base instead, so it says which SECTION you are in
 * rather than what the URL happens to end with.
 */
export function fileTabSegment(pathname: string): string | null {
  const fileId = loanFileIdFromPath(pathname);
  if (!fileId) return null;
  const rest = pathname.slice(`/loan-files/${fileId}`.length).replace(/^\/+|\/+$/g, "");
  return rest === "" ? null : (rest.split("/")[0] ?? null);
}

/** What the context column shows for `pathname`. `null` = show nothing. */
export function contextSection(pathname: string): ContextSection | null {
  const fileId = loanFileIdFromPath(pathname);
  if (fileId) return fileSections(fileId);
  if (pathname.startsWith("/admin")) return ADMIN_SECTION;
  // The pipeline's column is SavedViews (LP-UI-014) rather than a link list, so
  // it has no items here — but it does render, and the rail's ⌘B toggle is
  // gated on this returning non-null. An empty `items` says "there is a column,
  // and its contents are not routes".
  if (pathname === "/dashboard") return { title: "Pipeline", items: [] };
  return null;
}
