"use client";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";
import {
  type AdjustNeedInput,
  useAdjustNeed,
  useConfirmNeed,
  useDismissNeed,
  useWaiveNeed,
} from "@/lib/api/needs";
import { getErrorMessage } from "@/lib/errors/api-error";
import { isProposed } from "@/lib/loan-files/needs";
import type { NeedsItemPriority, NeedsItemPublic } from "@/lib/types/needs-item";
import { Check, MoreHorizontal, Pencil, SlashSquare, XCircle } from "lucide-react";
import { useId, useState } from "react";
import { toast } from "sonner";

/**
 * The disposition controls for one need (LP-70) — the human disposes. A proposed
 * need leads with a one-click **Confirm**; the overflow menu offers Adjust, Waive,
 * and (for a proposal) Dismiss. Each calls the audited write API and feeds the
 * correction signal. The buttons disable while a request is in flight.
 */
export function NeedActions({ fileId, need }: { fileId: string; need: NeedsItemPublic }) {
  const [dialog, setDialog] = useState<"adjust" | "dismiss" | "waive" | null>(null);

  const confirm = useConfirmNeed(fileId);
  const proposed = isProposed(need);
  const isSettled = need.status === "verified" || need.status === "waived";

  return (
    <div className="flex shrink-0 items-center gap-1.5">
      {proposed && (
        <Button
          size="sm"
          className="h-8 gap-1.5"
          disabled={confirm.isPending}
          onClick={() =>
            confirm.mutate(need.id, {
              onSuccess: () => toast.success("Need confirmed"),
              onError: (error) => toast.error(getErrorMessage(error)),
            })
          }
        >
          {confirm.isPending ? (
            <Spinner className="h-3.5 w-3.5" />
          ) : (
            <Check className="h-3.5 w-3.5" />
          )}
          Confirm
        </Button>
      )}

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            size="icon"
            variant="ghost"
            className="h-8 w-8 text-gray-400 hover:text-gray-600"
            aria-label={`Actions for ${need.title}`}
          >
            <MoreHorizontal className="h-4 w-4" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-44">
          <DropdownMenuItem onSelect={() => setDialog("adjust")}>
            <Pencil className="mr-2 h-4 w-4" /> Adjust
          </DropdownMenuItem>
          {!isSettled && (
            <DropdownMenuItem onSelect={() => setDialog("waive")}>
              <SlashSquare className="mr-2 h-4 w-4" /> Waive
            </DropdownMenuItem>
          )}
          {proposed && (
            <>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                onSelect={() => setDialog("dismiss")}
                className="text-destructive focus:text-destructive"
              >
                <XCircle className="mr-2 h-4 w-4" /> Dismiss
              </DropdownMenuItem>
            </>
          )}
        </DropdownMenuContent>
      </DropdownMenu>

      {dialog === "adjust" && (
        <AdjustDialog fileId={fileId} need={need} onClose={() => setDialog(null)} />
      )}
      {dialog === "dismiss" && (
        <ReasonDialog fileId={fileId} need={need} kind="dismiss" onClose={() => setDialog(null)} />
      )}
      {dialog === "waive" && (
        <ReasonDialog fileId={fileId} need={need} kind="waive" onClose={() => setDialog(null)} />
      )}
    </div>
  );
}

const PRIORITIES: NeedsItemPriority[] = ["blocking", "standard", "low"];

function AdjustDialog({
  fileId,
  need,
  onClose,
}: {
  fileId: string;
  need: NeedsItemPublic;
  onClose: () => void;
}) {
  const titleId = useId();
  const descId = useId();
  const priorityId = useId();
  const [title, setTitle] = useState(need.title);
  const [description, setDescription] = useState(need.description ?? "");
  const [priority, setPriority] = useState<NeedsItemPriority>(need.priority);
  const adjust = useAdjustNeed(fileId);

  function save() {
    const input: AdjustNeedInput = {
      title: title.trim(),
      description: description.trim() || null,
      priority,
    };
    adjust.mutate(
      { needId: need.id, input },
      {
        onSuccess: () => {
          toast.success("Need updated");
          onClose();
        },
        onError: (error) => toast.error(getErrorMessage(error)),
      },
    );
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Adjust need</DialogTitle>
          <DialogDescription>
            Edit what this need asks for. Saving marks it as a confirmed, real need.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <div className="space-y-1.5">
            <Label htmlFor={titleId}>Title</Label>
            <Input id={titleId} value={title} onChange={(event) => setTitle(event.target.value)} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor={descId}>Description</Label>
            <Textarea
              id={descId}
              value={description}
              placeholder="Optional detail for the borrower or your own notes"
              onChange={(event) => setDescription(event.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor={priorityId}>Priority</Label>
            <Select
              id={priorityId}
              value={priority}
              onChange={(event) => setPriority(event.target.value as NeedsItemPriority)}
            >
              {PRIORITIES.map((value) => (
                <option key={value} value={value}>
                  {value.charAt(0).toUpperCase() + value.slice(1)}
                </option>
              ))}
            </Select>
          </div>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose} disabled={adjust.isPending}>
            Cancel
          </Button>
          <Button onClick={save} disabled={adjust.isPending || !title.trim()}>
            {adjust.isPending && <Spinner className="mr-2 h-4 w-4" />}
            Save changes
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

const REASON_COPY = {
  dismiss: {
    title: "Dismiss need",
    description: "This proposal doesn't apply to the file. A note helps the AI learn.",
    placeholder: "Why doesn't this apply? (e.g. W-2 employee only — no business returns needed)",
    action: "Dismiss",
  },
  waive: {
    title: "Waive need",
    description: "Set this need aside as not required for the file, with a reason.",
    placeholder: "Why is this not required? (e.g. lender waived the reserve requirement)",
    action: "Waive",
  },
} as const;

function ReasonDialog({
  fileId,
  need,
  kind,
  onClose,
}: {
  fileId: string;
  need: NeedsItemPublic;
  kind: "dismiss" | "waive";
  onClose: () => void;
}) {
  const reasonId = useId();
  const [reason, setReason] = useState("");
  const dismiss = useDismissNeed(fileId);
  const waive = useWaiveNeed(fileId);
  const mutation = kind === "dismiss" ? dismiss : waive;
  const copy = REASON_COPY[kind];

  function submit() {
    mutation.mutate(
      { needId: need.id, reason: reason.trim() || undefined },
      {
        onSuccess: () => {
          toast.success(kind === "dismiss" ? "Need dismissed" : "Need waived");
          onClose();
        },
        onError: (error) => toast.error(getErrorMessage(error)),
      },
    );
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{copy.title}</DialogTitle>
          <DialogDescription>{copy.description}</DialogDescription>
        </DialogHeader>
        <div className="space-y-1.5 py-2">
          <Label htmlFor={reasonId}>Reason</Label>
          <Textarea
            id={reasonId}
            value={reason}
            placeholder={copy.placeholder}
            onChange={(event) => setReason(event.target.value)}
          />
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button
            variant={kind === "dismiss" ? "destructive" : "default"}
            onClick={submit}
            disabled={mutation.isPending}
          >
            {mutation.isPending && <Spinner className="mr-2 h-4 w-4" />}
            {copy.action}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
