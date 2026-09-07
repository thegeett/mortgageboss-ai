"use client";

import { PartyRequestDialog } from "@/components/file/communication/party-request-dialog";
import { Button } from "@/components/ui/button";
import { Users } from "lucide-react";
import { useState } from "react";

/**
 * The way in to writing to a party who is not the borrower (LP-835).
 *
 * Its own component so the page stays a list of panels rather than a component holding dialog state
 * — and so the dialog is mounted only while it is open, which keeps its `usePartyRequests` query off
 * every visit to the Communication page.
 */
export function PartyRequestButton({ fileId }: { fileId: string }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="gap-2"
        onClick={() => setOpen(true)}
      >
        <Users className="h-4 w-4" aria-hidden />
        Write to another party
      </Button>
      {open ? <PartyRequestDialog fileId={fileId} open={open} onOpenChange={setOpen} /> : null}
    </>
  );
}
