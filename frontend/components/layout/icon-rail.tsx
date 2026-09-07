"use client";

import { CONTEXT_COLUMN_ID } from "@/components/layout/context-column";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { contextSection, isNavItemActive, visibleNavItems } from "@/lib/navigation";
import { useAuthStore } from "@/lib/stores/auth-store";
import { cn } from "@/lib/utils";
import { Layers, PanelLeft } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

/**
 * The 52px icon rail (LP-UI-008) — the one piece of chrome that is identical on
 * every screen. Top-level destinations only; everything route-specific lives in
 * the context column beside it.
 *
 * Each item is an icon with no visible label, so each carries an accessible name
 * AND a tooltip: the name for assistive tech, the tooltip for the sighted user
 * who has not yet learned the glyphs.
 */
export function IconRail({
  collapsed,
  onToggleContext,
}: {
  collapsed: boolean;
  onToggleContext: () => void;
}) {
  const pathname = usePathname();
  const role = useAuthStore((state) => state.user?.role);
  const items = visibleNavItems(role);
  // ContextColumn renders nothing on a route with no section (/dev/*), and an
  // aria-controls pointing at an element that is not in the document is worse
  // than none at all.
  const hasColumn = contextSection(pathname) !== null;

  return (
    <nav
      aria-label="Main"
      className="hidden w-rail shrink-0 flex-col items-center gap-1 border-r border-border bg-card py-2 md:flex"
    >
      <Link
        href="/dashboard"
        aria-label="mortgageboss·ai — dashboard"
        className="mb-1 flex h-8 w-8 items-center justify-center rounded-md bg-primary text-primary-foreground"
      >
        <Layers className="h-4 w-4" />
      </Link>

      {items.map((item) => {
        const active = isNavItemActive(pathname, item);
        return (
          <Tooltip key={item.href}>
            <TooltipTrigger asChild>
              <Link
                href={item.href}
                aria-label={item.label}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex h-8 w-8 items-center justify-center rounded-md transition-colors",
                  active
                    ? "bg-primary/10 text-primary"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground",
                )}
              >
                <item.icon className="h-4 w-4" />
              </Link>
            </TooltipTrigger>
            <TooltipContent side="right">{item.label}</TooltipContent>
          </Tooltip>
        );
      })}

      <div className="flex-1" />

      {/* Only where there is a column to toggle. LP-UI-011 left the dashboard —
          the app's primary screen — with no context section, and a disclosure
          button that discloses nothing is a control that lies. Hidden rather
          than disabled: the rail is a column of icons separated by a spacer, so
          one fewer at the bottom reads as "nothing to toggle here" without
          adding a dead affordance to tab through. */}
      {hasColumn ? (
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              type="button"
              onClick={onToggleContext}
              aria-label="Toggle the context column"
              // A disclosure button has to say which way it is pointing; without
              // this the control is identical in both states to anyone who cannot
              // see the column. This is what the hook's React value is FOR — it
              // had no consumer at all, which is why it was free to drift.
              aria-expanded={!collapsed}
              aria-controls={CONTEXT_COLUMN_ID}
              aria-keyshortcuts="Meta+B Control+B"
              className="flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            >
              <PanelLeft className="h-4 w-4" />
            </button>
          </TooltipTrigger>
          <TooltipContent side="right">Toggle sidebar ⌘B</TooltipContent>
        </Tooltip>
      ) : null}
    </nav>
  );
}
