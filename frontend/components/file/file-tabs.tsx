"use client";

import { FILE_TABS, activeTabKey, tabHref } from "@/lib/loan-files/tabs";
import { cn } from "@/lib/utils";
import Link from "next/link";
import { usePathname } from "next/navigation";

/**
 * Route-based tab navigation for a file (LP-33). Each tab is a sub-route, so
 * these are links (not ARIA tabs/tabpanels) — the active link carries
 * `aria-current="page"`, derived from the pathname. Scrolls horizontally on
 * narrow screens.
 */
export function FileTabs({ fileId }: { fileId: string }) {
  const pathname = usePathname();
  const active = activeTabKey(pathname);

  return (
    <nav
      aria-label="File sections"
      className="-mb-px flex gap-1 overflow-x-auto border-b border-gray-200"
    >
      {FILE_TABS.map((tab) => {
        const isActive = tab.key === active;
        return (
          <Link
            key={tab.key}
            href={tabHref(fileId, tab.segment)}
            aria-current={isActive ? "page" : undefined}
            className={cn(
              "whitespace-nowrap border-b-2 px-3 py-2.5 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
              isActive
                ? "border-primary text-primary"
                : "border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-900",
            )}
          >
            {tab.label}
          </Link>
        );
      })}
    </nav>
  );
}
