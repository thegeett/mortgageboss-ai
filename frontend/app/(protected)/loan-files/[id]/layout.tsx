"use client";

import { FileError } from "@/components/file/file-error";
import { FileHeader } from "@/components/file/file-header";
import { FileTabs } from "@/components/file/file-tabs";
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
    // `-m-4` cancels the shell's page padding: the rail meets the window edge
    // and the border is the seam, which is the point of a full-bleed shell.
    <div className="-m-4 flex h-full min-h-0">
      <div className="min-w-0 flex-1 overflow-y-auto p-4">
        <div className="space-y-6">
          <div className="space-y-4">
            <FileHeader file={file} />
            <FileTabs fileId={id} />
          </div>
          {children}
        </div>
      </div>
      <FileContextRail fileId={id} />
    </div>
  );
}
