"use client";

/**
 * File-header actions (LP-79.5) — the overflow menu on the file workspace header.
 * Today it carries **Delete file** (soft-delete with a named confirmation); the menu
 * leaves room for future per-file actions. On a successful delete the file is gone
 * from the processor's views, so we navigate back to the dashboard.
 */

import { DeleteFileDialog } from "@/components/file/delete-file-dialog";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { LoanFileDetail } from "@/lib/types/loan-file";
import { MoreHorizontal, Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

export function FileHeaderActions({ file }: { file: LoanFileDetail }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            type="button"
            size="icon"
            variant="ghost"
            className="h-9 w-9 text-gray-400 hover:text-gray-700"
            aria-label="File actions"
          >
            <MoreHorizontal className="h-5 w-5" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-40">
          <DropdownMenuItem
            className="text-destructive focus:text-destructive"
            onSelect={() => setOpen(true)}
          >
            <Trash2 className="mr-2 h-4 w-4" /> Delete file
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <DeleteFileDialog
        file={file}
        open={open}
        onOpenChange={setOpen}
        onDeleted={() => router.push("/dashboard")}
      />
    </>
  );
}
