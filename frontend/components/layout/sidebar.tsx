"use client";

import { isActivePath, visibleNavItems } from "@/lib/navigation";
import { useAuthStore } from "@/lib/stores/auth-store";
import { cn } from "@/lib/utils";
import { Layers } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

/**
 * Desktop navigation sidebar (LP-27). The persistent left rail of the app shell:
 * wordmark + the role-filtered nav with an active-route indicator. Hidden below
 * `md`, where the same items appear in the header's mobile menu.
 */
export function Sidebar() {
  const pathname = usePathname();
  const role = useAuthStore((state) => state.user?.role);
  const items = visibleNavItems(role);

  return (
    <aside className="hidden w-60 shrink-0 border-r border-gray-200 bg-white md:flex md:flex-col">
      <div className="flex h-16 items-center border-b border-gray-200 px-5">
        <Link
          href="/dashboard"
          className="flex items-center gap-2.5 rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
        >
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-sm">
            <Layers className="h-4 w-4" />
          </span>
          <span className="text-base font-semibold tracking-tight text-gray-900">
            mortgageboss<span className="text-primary">·ai</span>
          </span>
        </Link>
      </div>

      <nav aria-label="Main" className="flex-1 space-y-1 p-3">
        {items.map((item) => {
          const active = isActivePath(pathname, item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={active ? "page" : undefined}
              className={cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
                active
                  ? "bg-primary/10 text-primary"
                  : "text-gray-600 hover:bg-gray-100 hover:text-gray-900",
              )}
            >
              <item.icon
                className={cn("h-4 w-4 shrink-0", active ? "text-primary" : "text-gray-400")}
              />
              {item.label}
            </Link>
          );
        })}
      </nav>

      <div className="border-t border-gray-200 p-3">
        <p className="px-3 text-xs text-gray-400">Phase 1 — Foundation</p>
      </div>
    </aside>
  );
}
