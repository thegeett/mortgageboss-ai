"use client";

import { ComposeRequestDialog } from "@/components/file/communication/compose-request-dialog";
import { Button } from "@/components/ui/button";
import { FilePlus } from "lucide-react";
import { useState } from "react";

/**
 * The way in to asking for a document nothing flagged (LP-833).
 *
 * Mounted only while open, like the party dialog: the catalog is 166 rows and the needs list is a
 * second query, and neither should run on every visit to the Communication page.
 */
export function ComposeRequestButton({ fileId }: { fileId: string }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button type="button" size="sm" className="gap-2" onClick={() => setOpen(true)}>
        <FilePlus className="h-4 w-4" aria-hidden />
        Request documents
      </Button>
      {open ? <ComposeRequestDialog fileId={fileId} open={open} onOpenChange={setOpen} /> : null}
    </>
  );
}
