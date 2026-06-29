"use client";

/**
 * Loan inline editor (LP-80.5) — reuses the shared EditableRow + the existing
 * PATCH /loan-files endpoint. Adds the **target lender** (which selects the LP-80
 * overlay) and **confirms a program change** (Conv ↔ FHA changes the whole rule set
 * + overlay, so it isn't a casual mis-click). Audited with from→to values + marks
 * verification stale. The note rate / amortization stay in the stated-data editor.
 */

import { EditableRow, type FieldDef } from "@/components/file/overview/editable-row";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useLenders } from "@/lib/api/lenders";
import { useUpdateLoanFile } from "@/lib/api/overview-edit";
import { getErrorMessage } from "@/lib/errors/api-error";
import { programLabel } from "@/lib/loan-files/labels";
import type { LoanFileDetail, LoanProgram } from "@/lib/types/loan-file";
import { LOAN_PROGRAM_OPTIONS, LOAN_PURPOSE_OPTIONS } from "@/lib/validation/intake";
import { useState } from "react";
import { toast } from "sonner";

export function LoanEditor({ file }: { file: LoanFileDetail }) {
  const update = useUpdateLoanFile(file.id);
  const lenders = useLenders();
  // A program change is held here until the processor confirms it.
  const [pending, setPending] = useState<Record<string, unknown> | null>(null);

  const fields: FieldDef[] = [
    { key: "loan_amount", label: "Amount", kind: "money" },
    { key: "loan_purpose", label: "Purpose", kind: "select", options: LOAN_PURPOSE_OPTIONS },
    { key: "loan_program", label: "Program", kind: "select", options: LOAN_PROGRAM_OPTIONS },
    {
      key: "lender_id",
      label: "Target lender",
      kind: "select",
      options: (lenders.data ?? []).map((l) => ({ value: l.id, label: l.name })),
    },
    { key: "loan_officer_name", label: "Loan officer", kind: "text" },
    { key: "loan_officer_email", label: "LO email", kind: "text" },
  ];

  function commit(changed: Record<string, unknown>) {
    update.mutate(changed, {
      onSuccess: () => toast.success("Loan updated"),
      onError: (e) => toast.error("Couldn't save the loan", { description: getErrorMessage(e) }),
    });
  }

  function onSave(changed: Record<string, unknown>) {
    // Changing the program swaps the entire rule set + overlay → confirm first.
    if ("loan_program" in changed) {
      setPending(changed);
      return;
    }
    commit(changed);
  }

  const nextProgram = (pending?.loan_program as LoanProgram | null) ?? null;

  return (
    <>
      <EditableRow
        fields={fields}
        initial={{
          loan_amount: file.loan_amount ?? "",
          loan_purpose: file.loan_purpose ?? "",
          loan_program: file.loan_program ?? "",
          lender_id: file.lender_id ?? "",
          loan_officer_name: file.loan_officer_name ?? "",
          loan_officer_email: file.loan_officer_email ?? "",
        }}
        onSave={onSave}
        busy={update.isPending}
      />

      <Dialog open={pending !== null} onOpenChange={(open) => !open && setPending(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Change the loan program?</DialogTitle>
            <DialogDescription className="pt-1 leading-relaxed">
              Changing the program to{" "}
              <span className="font-medium text-gray-900">{programLabel(nextProgram)}</span> changes
              which rules and lender overlay apply, and will require re-running verification.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="gap-2 sm:gap-2">
            <Button type="button" variant="ghost" onClick={() => setPending(null)}>
              Cancel
            </Button>
            <Button
              type="button"
              onClick={() => {
                if (pending) commit(pending);
                setPending(null);
              }}
            >
              Change program
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
