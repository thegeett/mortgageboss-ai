"use client";

import { FileError } from "@/components/file/file-error";
import { FileHeader } from "@/components/file/file-header";
import { FileTabs } from "@/components/file/file-tabs";
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
  const { data: file, isError, error } = useLoanFile(id);

  if (isError) {
    const notFound = isAxiosError(error) && error.response?.status === 404;
    return <FileError notFound={notFound} />;
  }

  return (
    <div className="space-y-6">
      <div className="space-y-4">
        <FileHeader file={file} />
        <FileTabs fileId={id} />
      </div>
      {children}
    </div>
  );
}
