"use client";

import { Breadcrumb } from "@/components/layout/breadcrumb";
import { UserMenu } from "@/components/layout/user-menu";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { humanize } from "@/lib/format";
import {
  activeItemHref,
  contextSection,
  isActivePath,
  isNavItemActive,
  visibleNavItems,
} from "@/lib/navigation";
import { useAuthStore } from "@/lib/stores/auth-store";
import { cn } from "@/lib/utils";
import { Menu } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

/**
 * Top header of the app shell (LP-27): a mobile nav menu (below `md`, where the
 * sidebar is hidden), the current section title, and the account menu. Reads the
 * user from the LP-25 store; renders nothing user-specific if absent.
 */
/**
 * A readable name for a route the nav does not list — the last path segment that
 * is not an id, humanised. `/admin/lenders` → "Lenders".
 */
function sectionFromPath(pathname: string): string {
  const segments = pathname.split("/").filter(Boolean);
  // Walk back past ids and uuids to the last word-shaped segment.
  const named = [...segments].reverse().find((s) => /^[a-z][a-z-]*$/i.test(s) && s.length > 1);
  if (!named) return "Pipeline";
  return humanize(named);
}

export function Header() {
  const pathname = usePathname();
  const user = useAuthStore((state) => state.user);
  const items = visibleNavItems(user?.role);
  const current = items.find((item) => isNavItemActive(pathname, item));
  // Below `md` the context column is hidden, and LP-UI-016 removed the file's
  // tab strip — which was the mobile affordance. Without this you can open a
  // file on a phone and have no way to reach Documents or Verification at all.
  // The column's own items, surfaced where the column cannot be.
  const section = contextSection(pathname);
  const sectionItems = section?.items ?? [];
  const currentHref = activeItemHref(
    pathname,
    sectionItems.map((item) => item.href),
  );

  return (
    <header className="flex h-[--topbar-h] shrink-0 items-center justify-between border-b border-border bg-card px-3">
      <div className="flex items-center gap-2">
        {/* Mobile nav: the sidebar is hidden below md, so surface the nav here. */}
        <DropdownMenu>
          <DropdownMenuTrigger
            aria-label="Open navigation menu"
            className="flex h-7 w-7 items-center justify-center rounded-md text-foreground-2 hover:bg-muted md:hidden"
          >
            <Menu className="h-5 w-5" />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-52">
            {items.map((item) => (
              <DropdownMenuItem key={item.href} asChild>
                <Link
                  href={item.href}
                  aria-current={isActivePath(pathname, item.href) ? "page" : undefined}
                >
                  <item.icon className="mr-2 h-4 w-4 text-muted-foreground" />
                  {item.label}
                </Link>
              </DropdownMenuItem>
            ))}
            {sectionItems.length > 0 ? (
              <>
                <DropdownMenuSeparator />
                <DropdownMenuLabel className="font-normal text-muted-foreground">
                  {section?.title}
                </DropdownMenuLabel>
                {sectionItems.map((item) => (
                  <DropdownMenuItem key={item.href} asChild>
                    <Link
                      href={item.href}
                      aria-current={item.href === currentHref ? "page" : undefined}
                    >
                      <item.icon className="mr-2 h-4 w-4 text-muted-foreground" />
                      {item.label}
                    </Link>
                  </DropdownMenuItem>
                ))}
              </>
            ) : null}
          </DropdownMenuContent>
        </DropdownMenu>

        {/* The fallback names WHERE YOU ARE, never the product (LP-UI-036). It
            is the page's h1, and on the admin routes — which are not nav items —
            it said "mortgageboss·ai", so a screen reader answered "where am I"
            with the product name. A humanised path segment is right for any
            route the nav does not list. */}
        <Breadcrumb fallback={current?.label ?? sectionFromPath(pathname)} />
      </div>

      {user && <UserMenu user={user} />}
    </header>
  );
}
