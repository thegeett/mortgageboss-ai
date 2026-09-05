"use client";

/**
 * LP-643 — the add-a-line control, one per DTI section.
 *
 * A row the CALCULATOR could not produce: a documented obligation the credit report missed, an
 * income source stated nowhere structured. It is not an override — an override changes the value of
 * a line the engine emitted, and this has no such line behind it.
 *
 * WHAT IT DOES NOT DO, and the server enforces this rather than the button: an added row does not
 * clear a gate. A gate says a required input is unknown, and an unrelated row does not make it
 * known. Overriding the gated line itself remains the way to supply that figure.
 */

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAddDtiLine } from "@/lib/api/dti";
import type { DtiCustomLineInput } from "@/lib/types/dti";
import { Plus, X } from "lucide-react";
import { useState } from "react";

export function DtiAddLine({
  fileId,
  section,
}: {
  fileId: string;
  section: DtiCustomLineInput["section"];
}) {
  const [open, setOpen] = useState(false);
  const [label, setLabel] = useState("");
  const [amount, setAmount] = useState("");
  const add = useAddDtiLine(fileId);

  // A label and a positive-looking amount. Validated again server-side; this is only to stop an
  // obviously-empty submission round-tripping.
  const ready = label.trim().length > 0 && amount.trim().length > 0 && Number(amount) >= 0;

  if (!open) {
    return (
      <Button
        variant="ghost"
        size="sm"
        className="mt-1 h-7 gap-1 px-2 text-xs text-gray-500 hover:text-gray-900"
        onClick={() => setOpen(true)}
      >
        <Plus className="h-3.5 w-3.5" aria-hidden />
        Add a line
      </Button>
    );
  }

  return (
    <div className="mt-2 flex items-start gap-2 rounded-md border border-gray-200 bg-gray-50/60 p-2">
      <Input
        aria-label="Description"
        value={label}
        onChange={(event) => setLabel(event.target.value)}
        placeholder="Description"
        className="h-8 flex-1 text-sm"
      />
      <Input
        aria-label="Monthly amount"
        value={amount}
        onChange={(event) => setAmount(event.target.value)}
        placeholder="0.00"
        inputMode="decimal"
        className="h-8 w-28 text-sm"
      />
      <Button
        size="sm"
        className="h-8"
        disabled={!ready || add.isPending}
        onClick={() =>
          add.mutate(
            { section, label: label.trim(), amount: amount.trim() },
            {
              onSuccess: () => {
                setLabel("");
                setAmount("");
                setOpen(false);
              },
            },
          )
        }
      >
        {add.isPending ? "Adding…" : "Add"}
      </Button>
      <Button
        variant="ghost"
        size="sm"
        className="h-8 w-8 p-0"
        aria-label="Cancel"
        onClick={() => {
          setLabel("");
          setAmount("");
          setOpen(false);
        }}
      >
        <X className="h-4 w-4" aria-hidden />
      </Button>
    </div>
  );
}
