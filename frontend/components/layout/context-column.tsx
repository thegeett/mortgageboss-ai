"use client";

import { activeItemHref, contextSection } from "@/lib/navigation";
import { cn } from "@/lib/utils";
import Link from "next/link";
import { usePathname } from "next/navigation";

/** Referenced by the rail's toggle via `aria-controls`. */
export const CONTEXT_COLUMN_ID = "context-column";

/**
 * The 216px context column (LP-UI-008). What it holds depends on the route:
 * pipeline destinations on the dashboard, this file's sections inside a file,
 * the admin sections in admin.
 *
 * Collapse is driven by `--nav-w` on the document element, which the server sets
 * from a cookie before first paint (see `app/layout.tsx`). This component does
 * not read the state at all — it just occupies `w-nav`, which is `0` when
 * collapsed. That is what makes the collapsed state survive a hard refresh with
 * no flash: there is no client effect in the path.
 */
export function ContextColumn() {
  const pathname = usePathname();
  const section = contextSection(pathname);
  // Computed once for the list rather than per item: "current" is a property of
  // the whole set (the most specific match), not of any item on its own.
  const currentHref = activeItemHref(
    pathname,
    section ? section.items.map((item) => item.href) : [],
  );

  if (!section) return null;

  return (
    <div
      // `w-nav` reads --nav-w; at 0 the column must not still claim its border.
      id={CONTEXT_COLUMN_ID}
      className="hidden w-nav shrink-0 overflow-hidden border-r border-border bg-card transition-[width] duration-150 md:block"
      data-context-column
    >
      <nav aria-label={section.title} className="w-nav p-2">
        <p className="px-2 pb-1 pt-1 text-label uppercase text-muted-foreground">{section.title}</p>
        {section.items.map((item) => {
          const active = item.href === currentHref;
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={active ? "page" : undefined}
              className={cn(
                "flex h-7 items-center gap-2 rounded-md px-2 text-sm transition-colors",
                active
                  ? "bg-primary/10 font-medium text-primary"
                  : "text-foreground-2 hover:bg-muted hover:text-foreground",
              )}
            >
              <item.icon className="h-3.5 w-3.5 shrink-0" />
              <span className="truncate">{item.label}</span>
            </Link>
          );
        })}
      </nav>
    </div>
  );
}
