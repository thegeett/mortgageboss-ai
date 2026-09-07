import { cn } from "@/lib/utils";
import { Ban, FolderOpen, SearchX } from "lucide-react";
import type { ReactNode } from "react";

/**
 * The three empty states (LP-UI-034), and they are three because they mean three
 * different things.
 *
 *   nothing-yet   The list is real and has no rows. Say what goes here and offer
 *                 the ONE action that fills it.
 *   filtered      There are rows; this query hides them. Name the filter and the
 *                 query, and offer the way back to the full list.
 *   structural    Correct to be empty. It gets NO action, because there is
 *                 nothing to do and offering something would imply otherwise.
 *
 * Collapsing them is the common mistake and it misleads in both directions: a
 * processor who filtered to nothing is told they have no documents, and a
 * processor whose tab is empty by design goes looking for the upload button.
 *
 * The icon is a second channel on the same distinction, not decoration — the
 * three are deliberately unalike in silhouette.
 */

export type EmptyKind = "nothing-yet" | "filtered" | "structural";

const ICON = {
  "nothing-yet": FolderOpen,
  filtered: SearchX,
  structural: Ban,
} as const;

export function EmptyState({
  kind,
  title,
  children,
  action,
  className,
}: {
  kind: EmptyKind;
  /** What this is, in the processor's words. Not "No data". */
  title: string;
  /**
   * Why it is empty and what would change it. For `filtered`, name the actual
   * filter and query — "Nothing in Blocked to submit matches ellis" tells a
   * processor what to undo; "No results" tells them nothing.
   */
  children: ReactNode;
  /**
   * The one action that fills it. Structural states must not have one: there is
   * nothing to do, and a button would say there is.
   */
  action?: ReactNode;
  className?: string;
}) {
  const Icon = ICON[kind];
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-2 px-6 py-10 text-center",
        className,
      )}
    >
      <span className="flex h-9 w-9 items-center justify-center rounded-md border border-border bg-muted/50">
        <Icon className="h-4 w-4 text-muted-foreground" aria-hidden />
      </span>
      <p className="mt-1 text-sm font-semibold text-foreground">{title}</p>
      <p className="max-w-xs text-pretty text-sm text-muted-foreground">{children}</p>
      {kind === "structural" ? null : action ? <div className="mt-2">{action}</div> : null}
    </div>
  );
}
