"use client";

import { UserMenu } from "@/components/layout/user-menu";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { isActivePath, visibleNavItems } from "@/lib/navigation";
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
  const current = items.find((item) => isActivePath(pathname, item.href));

  return (
    <header className="flex h-16 shrink-0 items-center justify-between border-b border-gray-200 bg-white px-4 sm:px-6">
      <div className="flex items-center gap-2">
        {/* Mobile nav: the sidebar is hidden below md, so surface the nav here. */}
        <DropdownMenu>
          <DropdownMenuTrigger
            aria-label="Open navigation menu"
            className="flex h-9 w-9 items-center justify-center rounded-md text-gray-600 hover:bg-gray-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 md:hidden"
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
                  <item.icon className="mr-2 h-4 w-4 text-gray-400" />
                  {item.label}
                </Link>
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>

        <h1 className={cn("text-base font-semibold text-gray-900")}>
          {current?.label ?? "mortgageboss·ai"}
        </h1>
      </div>

      {user && <UserMenu user={user} />}
    </header>
  );
}
