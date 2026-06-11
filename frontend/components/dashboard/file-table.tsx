"use client";

import { StatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { LoanFileSummary } from "@/lib/types/loan-file";
import { formatDistanceToNow } from "date-fns";
import { FolderPlus, SearchX, TriangleAlert } from "lucide-react";

const COLUMNS = ["File ID", "Borrower", "Property", "Status", "Lender", "Last activity"] as const;

function lastActivity(iso: string): string {
  try {
    return formatDistanceToNow(new Date(iso), { addSuffix: true });
  } catch {
    return "—";
  }
}

function HeaderRow() {
  return (
    <TableHeader>
      <TableRow className="hover:bg-transparent">
        {COLUMNS.map((col) => (
          <TableHead
            key={col}
            className="text-xs font-medium uppercase tracking-wide text-gray-400"
          >
            {col}
          </TableHead>
        ))}
      </TableRow>
    </TableHeader>
  );
}

function LoadingRows() {
  return (
    <TableBody>
      {Array.from({ length: 6 }, (_, i) => i).map((row) => (
        <TableRow key={row}>
          {COLUMNS.map((col) => (
            <TableCell key={col}>
              <Skeleton className="h-4 w-24" />
            </TableCell>
          ))}
        </TableRow>
      ))}
    </TableBody>
  );
}

/** A centered state panel (empty / error) spanning the table width. */
function StatePanel({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-16 text-center">
      {children}
    </div>
  );
}

export function FileTable({
  files,
  isPending,
  isError,
  isFiltered,
  onSelect,
  onNewFile,
}: {
  files: LoanFileSummary[];
  isPending: boolean;
  isError: boolean;
  isFiltered: boolean;
  onSelect: (file: LoanFileSummary) => void;
  onNewFile: () => void;
}) {
  if (isError) {
    return (
      <StatePanel>
        <TriangleAlert className="h-8 w-8 text-destructive" />
        <h3 className="mt-3 text-sm font-semibold text-gray-900">Couldn&apos;t load loan files</h3>
        <p className="mt-1 max-w-sm text-sm text-gray-500">
          Something went wrong fetching your files. Check your connection and try again.
        </p>
      </StatePanel>
    );
  }

  if (isPending) {
    return (
      <Table>
        <HeaderRow />
        <LoadingRows />
      </Table>
    );
  }

  if (files.length === 0) {
    return isFiltered ? (
      <StatePanel>
        <SearchX className="h-8 w-8 text-gray-300" />
        <h3 className="mt-3 text-sm font-semibold text-gray-900">No matching files</h3>
        <p className="mt-1 max-w-sm text-sm text-gray-500">
          No loan files match your current filters. Try clearing the search or a different filter.
        </p>
      </StatePanel>
    ) : (
      <StatePanel>
        <span className="flex h-12 w-12 items-center justify-center rounded-full bg-primary/10 text-primary">
          <FolderPlus className="h-6 w-6" />
        </span>
        <h3 className="mt-4 text-sm font-semibold text-gray-900">No loan files yet</h3>
        <p className="mt-1 max-w-sm text-sm text-gray-500">
          Create your first loan file to start assembling documents and tracking requirements.
        </p>
        <Button type="button" onClick={onNewFile} className="mt-5 gap-2">
          <FolderPlus className="h-4 w-4" />
          Create your first file
        </Button>
      </StatePanel>
    );
  }

  return (
    <Table>
      <HeaderRow />
      <TableBody>
        {files.map((file) => (
          <TableRow
            key={file.id}
            onClick={() => onSelect(file)}
            className="cursor-pointer"
            tabIndex={0}
            onKeyDown={(event) => {
              if (event.key === "Enter") onSelect(file);
            }}
          >
            <TableCell className="font-medium text-gray-900">{file.display_id}</TableCell>
            <TableCell className="text-gray-700">{file.primary_borrower_name ?? "—"}</TableCell>
            <TableCell className="max-w-[16rem] truncate text-gray-700">
              {file.property_address ?? "—"}
            </TableCell>
            <TableCell>
              <StatusBadge status={file.status} />
            </TableCell>
            <TableCell className="text-gray-700">{file.lender_name ?? "—"}</TableCell>
            <TableCell className="whitespace-nowrap text-gray-500">
              {lastActivity(file.updated_at)}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
