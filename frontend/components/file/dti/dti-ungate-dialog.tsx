"use client";

/**
 * LP-643 — the ungate confirmation: an ITEMISED CONSENT, not an "are you sure".
 *
 * The gate exists to stop a confident ratio resting on a value nobody established. This is the
 * control that switches it off, so the dialog's job is to make that a decision rather than a slip —
 * and a warning a reader skims is a warning that does nothing.
 *
 * Everything shown here comes from `GET /dti/ungate`, computed server-side by running the real
 * calculator with the same overrides Apply will write. Nothing is derived in this component: a
 * preview computed a second way can diverge from what Apply delivers, and a consent screen showing a
 * number the action does not produce is worse than showing none.
 */

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { SkeletonText } from "@/components/ui/skeleton";
import { useApplyDtiUngate, useDtiUngatePreview } from "@/lib/api/dti";
import { formatPercent } from "@/lib/format";
import { AlertTriangle, Lock } from "lucide-react";
import { useState } from "react";

export function DtiUngateDialog({
  fileId,
  open,
  onOpenChange,
}: {
  fileId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { data, isPending } = useDtiUngatePreview(fileId, open);
  const apply = useApplyDtiUngate(fileId);
  const [note, setNote] = useState("");

  const nothingToDo = data !== undefined && data.lines.length === 0;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Lock className="h-4 w-4 text-warning" />
            Record these inputs as $0.00?
          </DialogTitle>
          <DialogDescription>
            The DTI is gated because these inputs could not be established. Recording them as zero
            computes the ratio as if they do not exist.
          </DialogDescription>
        </DialogHeader>

        {isPending && <SkeletonText lines={4} />}

        {data && (
          <div className="space-y-4 text-sm">
            {/* EVERY LINE BY NAME. A processor recognises "Property taxes"; they cannot act on
                "3 values" — and the assertion, not the number, is what they can judge. */}
            {data.lines.length > 0 && (
              <ul className="space-y-2">
                {data.lines.map((line) => (
                  <li
                    key={line.key}
                    className="rounded-md border border-warning/40 bg-warning/5 p-3"
                  >
                    <p className="font-medium text-gray-900">{line.label}</p>
                    <p className="mt-0.5 text-gray-600">{line.assertion}</p>
                  </li>
                ))}
              </ul>
            )}

            {/* THE NUMBER IS WHAT THE CONSENT IS REALLY ABOUT. */}
            {data.lines.length > 0 && (
              <div className="rounded-md border border-gray-200 p-3">
                <p className="text-xs font-medium uppercase tracking-wide text-gray-500">
                  The ratio you will get
                </p>
                <dl className="mt-2 grid grid-cols-2 gap-2">
                  <div>
                    <dt className="text-xs text-gray-500">Front-end</dt>
                    <dd className="text-gray-900">
                      {formatPercent(data.front_end_before) ?? "gated"} →{" "}
                      <span className="font-semibold">
                        {formatPercent(data.front_end_after) ?? "still gated"}
                      </span>
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-gray-500">Back-end</dt>
                    <dd className="text-gray-900">
                      {formatPercent(data.back_end_before) ?? "gated"} →{" "}
                      <span className="font-semibold">
                        {formatPercent(data.back_end_after) ?? "still gated"}
                      </span>
                    </dd>
                  </div>
                </dl>
              </div>
            )}

            {/* WHAT WILL NOT MOVE. A processor who applies this, finds the file still gated, and is
                told nothing about which part did not move has been told LESS than before they
                clicked — the failure this whole dialog is written against. */}
            {data.unresolved.length > 0 && (
              <div
                role="note"
                className="flex items-start gap-2 rounded-md border border-gray-200 bg-gray-50 p-3"
              >
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-gray-400" aria-hidden />
                <div>
                  <p className="font-medium text-gray-900">
                    {nothingToDo
                      ? "This cannot be resolved by recording zeros"
                      : "This will still be gated afterwards"}
                  </p>
                  {data.unresolved.map((reason) => (
                    <p key={reason} className="mt-1 text-gray-600">
                      {reason}
                    </p>
                  ))}
                </div>
              </div>
            )}

            {data.lines.length > 0 && (
              <div>
                <label
                  htmlFor="ungate-note"
                  className="text-xs font-medium uppercase tracking-wide text-gray-500"
                >
                  Why (recorded on the file)
                </label>
                <Input
                  id="ungate-note"
                  value={note}
                  onChange={(event) => setNote(event.target.value)}
                  placeholder="e.g. property is tax-exempt — confirmed with the county"
                  className="mt-1"
                />
              </div>
            )}
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            // Disabled where there is nothing to record, rather than applying an empty change and
            // leaving a processor to wonder whether it worked.
            disabled={isPending || nothingToDo || apply.isPending}
            onClick={() =>
              apply.mutate(note.trim() || null, {
                onSuccess: () => {
                  setNote("");
                  onOpenChange(false);
                },
              })
            }
          >
            {apply.isPending ? "Applying…" : "Record as $0.00"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
