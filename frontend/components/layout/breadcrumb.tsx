"use client";

import { useLoanFile } from "@/lib/api/loan-files";
import { NEW_FILE_PATH, loanFileIdFromPath } from "@/lib/navigation";
import Link from "next/link";
import { usePathname } from "next/navigation";

/**
 * The topbar breadcrumb (LP-UI-016).
 *
 * Replaces the "Back to dashboard" link that used to sit above the file header.
 * A back link says only where you came from; a breadcrumb says where you ARE and
 * offers the way out as a side effect — and it belongs in the chrome, not on the
 * work surface, because it is true of the whole screen rather than of the file.
 *
 * Reads the file through the same cached query the layout already made, so it
 * costs no request.
 */
export function Breadcrumb({ fallback }: { fallback: string }) {
  const pathname = usePathname();
  const fileId = loanFileIdFromPath(pathname);

  // `/loan-files/new` is a page, not a file, so `loanFileIdFromPath` returns
  // null and this fell through to the fallback — which is the CURRENT NAV
  // ITEM's label, and the dashboard owns `/loan-files`. The topbar therefore
  // said "Dashboard" while a processor was creating a file, naming where they
  // were as somewhere else. It is also the only way back from this page.
  if (pathname === NEW_FILE_PATH) {
    return <Trail>New file</Trail>;
  }
  if (!fileId) {
    return <h1 className="text-sm font-semibold text-foreground">{fallback}</h1>;
  }
  return <FileCrumb fileId={fileId} />;
}

/** Pipeline / <where you are>. The shape every crumb on this app shares. */
function Trail({ children }: { children: React.ReactNode }) {
  return (
    <nav aria-label="Breadcrumb" className="flex min-w-0 items-center gap-1.5 text-sm">
      <Link
        href="/dashboard"
        className="shrink-0 text-muted-foreground transition-colors hover:text-foreground"
      >
        Pipeline
      </Link>
      <span aria-hidden className="text-muted-foreground">
        /
      </span>
      {/* The current location is the page's H1 (LP-UI-036). Every other route
          already gets its h1 from this component; `/loan-files/new` took this
          branch and had NONE, so nothing announced what the page was. One h1 per
          route, always in the same place, from the same component. */}
      <h1 className="truncate text-sm font-semibold text-foreground">{children}</h1>
    </nav>
  );
}

function FileCrumb({ fileId }: { fileId: string }) {
  const { data: file } = useLoanFile(fileId);

  return (
    <nav aria-label="Breadcrumb" className="flex min-w-0 items-center gap-1.5 text-sm">
      <Link
        href="/dashboard"
        className="shrink-0 text-muted-foreground transition-colors hover:text-foreground"
      >
        Pipeline
      </Link>
      <span aria-hidden className="text-muted-foreground">
        /
      </span>
      {/* Before the file RESOLVES this is the id from the URL, which is real and
          already on screen — a skeleton here would flicker a word into a bar and
          back for a cached query that usually resolves instantly.
          Once it has resolved, a file with no borrower reads "Unnamed file",
          the same words FileHeader uses three feet below. Falling back to the id
          there printed it twice on one line, beside the chip that already
          carries it, and gave the screen two answers to what the file is called. */}
      <span className="truncate font-semibold text-foreground">
        {file ? (file.primary_borrower_name ?? "Unnamed file") : fileId}
      </span>
      {file ? (
        <span className="tabular shrink-0 rounded bg-muted px-1.5 py-0.5 font-mono text-xs text-foreground-2">
          {file.display_id}
        </span>
      ) : null}
    </nav>
  );
}
