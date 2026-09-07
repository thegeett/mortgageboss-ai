"use client";

import { ErrorBoundary } from "@/components/error-boundary";
import { ContextColumn } from "@/components/layout/context-column";
import { Header } from "@/components/layout/header";
import { IconRail } from "@/components/layout/icon-rail";
import { TooltipProvider } from "@/components/ui/tooltip";
import { useNavCollapse } from "@/hooks/use-nav-collapse";
import { contextSection } from "@/lib/navigation";
import { usePathname } from "next/navigation";

/**
 * The authenticated app shell (LP-27, rebuilt in LP-UI-008).
 *
 * Four regions, full-bleed:
 *
 *   52px       216px            flex-1                288px
 *   icon rail  context column   work surface          file context rail
 *
 * The `max-w-6xl` wrapper is gone. It capped the densest screen in the product
 * at 1152px, which on a 1600px display threw away a quarter of the width a
 * processor was looking at. The file context rail is LP-UI-009.
 *
 * The content area keeps its own error boundary (LP-46): a crash in a page
 * leaves the rail and the column usable, so the user can navigate away.
 */
export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  // Whether there is a column to collapse at all. LP-UI-011 left the dashboard
  // with no context section, so both the shortcut and the rail's button are
  // gated on this rather than acting on a column that is not there.
  const hasColumn = contextSection(pathname) !== null;
  const { collapsed, toggle } = useNavCollapse({ enabled: hasColumn });

  return (
    <TooltipProvider delayDuration={200}>
      <div className="flex h-screen overflow-hidden bg-background">
        <IconRail collapsed={collapsed} onToggleContext={toggle} />
        <ContextColumn />
        <div className="flex min-w-0 flex-1 flex-col">
          <Header />
          {/* Full-bleed: no max-width. The padding is the work surface's own
              breathing room, not a column cap — a table inside a screen ticket
              can still opt out of it. */}
          <main className="flex-1 overflow-y-auto p-[var(--shell-pad)]">
            <ErrorBoundary headingLevel={2}>{children}</ErrorBoundary>
          </main>
        </div>
      </div>
    </TooltipProvider>
  );
}
