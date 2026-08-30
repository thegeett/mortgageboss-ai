"use client";

import { Breadcrumb } from "@/components/layout/breadcrumb";
import { UserMenu } from "@/components/layout/user-menu";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { isActivePath, isNavItemActive, visibleNavItems } from "@/lib/navigation";
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
export function Header() {
  const pathname = usePathname();
  const user = useAuthStore((state) => state.user);
  const items = visibleNavItems(user?.role);
  const current = items.find((item) => isNavItemActive(pathname, item));

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
          </DropdownMenuContent>
        </DropdownMenu>

        <Breadcrumb fallback={current?.label ?? "mortgageboss·ai"} />
      </div>

      {user && <UserMenu user={user} />}
    </header>
  );
}
