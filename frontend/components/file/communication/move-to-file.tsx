"use client";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useMoveMessage } from "@/lib/api/inbound";
import { useLoanFiles } from "@/lib/api/loan-files";
import { getErrorMessage } from "@/lib/errors/api-error";
import { notifySuccess } from "@/lib/toast";
import { useState } from "react";

/**
 * Move an unmatched email to a file (LP-1009). The list is this company's files, from the same search
 * the dashboard uses: it matches the file code or a borrower's name.
 */
export function MoveToFile({ messageId }: { messageId: string }) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const term = search.trim();
  const files = useLoanFiles({ search: term, pageSize: 8 }, { enabled: open && term.length > 0 });
  const move = useMoveMessage();
  const results = term.length > 0 ? (files.data?.items ?? []) : [];

  return (
    <>
      <Button type="button" size="sm" variant="outline" onClick={() => setOpen(true)}>
        Move to file
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Move to file</DialogTitle>
            <DialogDescription>Search by file code or borrower name.</DialogDescription>
          </DialogHeader>
          <Input
            aria-label="Search for a file"
            placeholder="LF-7K3M or a borrower's name"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
          {term.length > 0 && !files.isPending && results.length === 0 ? (
            <p className="text-sm text-muted-foreground">No file matches that.</p>
          ) : null}
          <ul className="flex flex-col gap-1">
            {results.map((file) => (
              <li key={file.id}>
                <button
                  type="button"
                  disabled={move.isPending}
                  className="flex w-full items-center justify-between gap-3 rounded-md px-2 py-1.5 text-left text-sm hover:bg-muted"
                  onClick={() =>
                    move.mutate(
                      { messageId, fileId: file.id },
                      {
                        onSuccess: () => {
                          setOpen(false);
                          notifySuccess({
                            title: `Moved to ${file.display_id}`,
                            consequence: "It is on that file's Communication tab.",
                          });
                        },
                      },
                    )
                  }
                >
                  <span className="font-medium text-foreground">{file.display_id}</span>
                  <span className="truncate text-muted-foreground">
                    {file.primary_borrower_name ?? "No borrower yet"}
                  </span>
                </button>
              </li>
            ))}
          </ul>
          {move.isError ? (
            <p className="text-sm text-danger">{getErrorMessage(move.error)}</p>
          ) : null}
        </DialogContent>
      </Dialog>
    </>
  );
}
