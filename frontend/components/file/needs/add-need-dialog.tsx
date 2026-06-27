"use client";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";
import { useAddNeed } from "@/lib/api/needs";
import { getErrorMessage } from "@/lib/errors/api-error";
import type { NeedsItemPriority } from "@/lib/types/needs-item";
import { Plus } from "lucide-react";
import { useId, useState } from "react";
import { toast } from "sonner";

const PRIORITIES: NeedsItemPriority[] = ["blocking", "standard", "low"];

/**
 * Add a need the AI missed (LP-70) — a processor-authored, confirmed need (and a
 * correction signal). A small dialog: a title is required; description, type, and
 * priority are optional.
 */
export function AddNeedDialog({ fileId }: { fileId: string }) {
  const [open, setOpen] = useState(false);
  const titleId = useId();
  const descId = useId();
  const typeId = useId();
  const priorityId = useId();

  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [needsType, setNeedsType] = useState("");
  const [priority, setPriority] = useState<NeedsItemPriority>("standard");
  const add = useAddNeed(fileId);

  function reset() {
    setTitle("");
    setDescription("");
    setNeedsType("");
    setPriority("standard");
  }

  function submit() {
    add.mutate(
      {
        title: title.trim(),
        description: description.trim() || null,
        needs_type: needsType.trim() || null,
        priority,
      },
      {
        onSuccess: () => {
          toast.success("Need added");
          reset();
          setOpen(false);
        },
        onError: (error) => toast.error(getErrorMessage(error)),
      },
    );
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) reset();
      }}
    >
      <DialogTrigger asChild>
        <Button size="sm" variant="outline" className="h-8 gap-1.5">
          <Plus className="h-4 w-4" /> Add need
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add a need</DialogTitle>
          <DialogDescription>
            Add something the file requires that isn't already listed.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <div className="space-y-1.5">
            <Label htmlFor={titleId}>Title</Label>
            <Input
              id={titleId}
              value={title}
              placeholder="e.g. Homeowner's insurance declaration"
              onChange={(event) => setTitle(event.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor={descId}>Description</Label>
            <Textarea
              id={descId}
              value={description}
              placeholder="Optional detail"
              onChange={(event) => setDescription(event.target.value)}
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor={typeId}>Document type</Label>
              <Input
                id={typeId}
                value={needsType}
                placeholder="e.g. insurance"
                onChange={(event) => setNeedsType(event.target.value)}
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
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => setOpen(false)} disabled={add.isPending}>
            Cancel
          </Button>
          <Button onClick={submit} disabled={add.isPending || !title.trim()}>
            {add.isPending && <Spinner className="mr-2 h-4 w-4" />}
            Add need
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
