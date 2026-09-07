"use client";

import { FileError } from "@/components/file/file-error";
import { FileHeader } from "@/components/file/file-header";
import { FileContextRail } from "@/components/layout/file-context-rail";
import { useLoanFile } from "@/lib/api/loan-files";
import { isAxiosError } from "axios";
import { useParams } from "next/navigation";

/**
 * File workspace shell (LP-33). A nested layout that fetches the file once and
 * renders the persistent header + tab navigation; each tab is a page rendering
 * into {children}, so the header/tabs stay put while you switch tabs.
 *
 * The header shows a skeleton while loading; a 404 (missing or out-of-company —
 * tenant-safe) shows "File not found". Tabs/placeholders don't need the file
 * data, so children render immediately; data-driven tab content (LP-34+) fetches
 * the same query itself (deduped by React Query).
 */
export default function FileLayout({ children }: { children: React.ReactNode }) {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const { data: file, isError, error, refetch } = useLoanFile(id);

  if (isError) {
    const notFound = isAxiosError(error) && error.response?.status === 404;
    return <FileError notFound={notFound} onRetry={() => void refetch()} />;
  }

  return (
    // The rail is a sibling of the work surface, not inside it, so it scrolls
    // independently and keeps the four numbers on screen while the tab scrolls.
    // The negative margin cancels the shell's page padding: the rail meets the
    // window edge and the border is the seam, which is the point of a full-bleed
    // shell.
    //
    // The height calc is the half that is easy to miss. A negative margin is
    // absorbed by an AUTO width — which is why the horizontal edges came out
    // right — but `height: 100%` is not auto: it resolves against the parent's
    // CONTENT box, so it was already 2×pad short before the margins moved it up
    // by one pad, leaving the rail's border ending a full 32px above the bottom
    // of the window. Adding the padding back to the height is what makes the
    // vertical seam behave like the horizontal one.
    <div className="-m-[var(--shell-pad)] flex h-[calc(100%_+_var(--shell-pad)_*_2)] min-h-0">
      <div className="min-w-0 flex-1 overflow-y-auto p-4">
        <div className="space-y-4">
          {/* The tab strip is gone (LP-UI-016). The shell's context column has
              carried these six sections since LP-UI-008, and two navigations one
              above the other is an unfinished migration, not a convenience. */}
          <FileHeader file={file} />
          {children}
        </div>
      </div>
      <FileContextRail fileId={id} />
    </div>
  );
}
