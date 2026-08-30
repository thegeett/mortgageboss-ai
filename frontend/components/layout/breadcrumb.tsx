"use client";

import { useLoanFile } from "@/lib/api/loan-files";
import { loanFileIdFromPath } from "@/lib/navigation";
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

  if (!fileId) {
    return <h1 className="text-sm font-semibold text-foreground">{fallback}</h1>;
  }
  return <FileCrumb fileId={fileId} />;
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
      {/* Before the file resolves this is the id from the URL, which is real and
          already on screen — a skeleton here would flicker a word into a bar and
          back for a cached query that usually resolves instantly. */}
      <span className="truncate font-semibold text-foreground">
        {file?.primary_borrower_name ?? fileId}
      </span>
      {file ? (
        <span className="tabular shrink-0 rounded bg-muted px-1.5 py-0.5 font-mono text-xs text-foreground-2">
          {file.display_id}
        </span>
      ) : null}
    </nav>
  );
}
