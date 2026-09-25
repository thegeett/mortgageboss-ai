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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";
import { useAddCondition } from "@/lib/api/conditions";
import { getErrorMessage } from "@/lib/errors/api-error";
import { notifyError, notifySuccess } from "@/lib/toast";
import { BUCKET_KIND_LABEL } from "@/lib/types/conditions";
import type { BucketKind, ConditionRound } from "@/lib/types/conditions";
import { useId, useState } from "react";

/** `2026-08-28` → `08/28/2026`, the form S1-12's sentence uses. */
function usDate(iso: string): string {
  const [year, month, day] = iso.split("-");
  return year && month && day ? `${month}/${day}/${year}` : iso;
}

/**
 * Which round this condition joins, in the words S1-12 specifies.
 *
 * ⚠️ TWO SENTENCES, AND THE SECOND ONE IS NOT A FALLBACK FOR MISSING DATA. "Starts round 1 (typed)"
 * is what happens on a file with no imported round: the server opens one. Rendering the first
 * sentence with a blank number would describe a round that does not exist yet; saying nothing would
 * leave a processor unable to tell whether they are adding to the lender's list or beginning one.
 *
 * ⚠️ `round_number` IS NULL ON A DRAFT — it is assigned on IMPORT — so a file whose only round is
 * still being reviewed is "starts round 1" too, which is correct: the backend attaches a manual
 * condition to the latest IMPORTED round, not to a draft somebody is mid-review on.
 */
function roundSentence(rounds: ConditionRound[] | undefined): string {
  const imported = (rounds ?? []).find(
    (round) => round.status === "imported" && round.round_number !== null,
  );
  if (!imported) return "Starts round 1 (typed).";
  return `Goes into round ${imported.round_number} (${usDate(imported.round_date)}), the latest imported round.`;
}

const HEADINGS = Object.keys(BUCKET_KIND_LABEL) as BucketKind[];

/**
 * Add one condition by hand (screen S1-12, `POST /loan-files/{id}/conditions`).
 *
 * ⚠️ THE WORDING FIELD IS SERIF AND REQUIRED, AND BOTH ARE RULES RATHER THAN STYLE. The design pack's
 * rule 2: text quoted from a document is IBM Plex Serif, because it is the lender's words and not
 * ours. Required, because a condition with no wording is not a condition — and the hint says "Type
 * it exactly as the lender wrote it", which is the same verbatim-storage promise the readers make
 * (spec §9.1: the lender's exact words, only whitespace normalised).
 *
 * ⚠️ NO STATUS CONTROL, AND THERE NEVER IS ONE IN STAGE 1 (design rule 3). Nothing here says
 * cleared, done, satisfied or open. A manually added condition arrives exactly as a parsed one does.
 */
export function AddConditionDialog({
  fileId,
  rounds,
  open,
  onOpenChange,
}: {
  fileId: string;
  /** The file's rounds, so the dialog can say which one this joins. */
  rounds: ConditionRound[] | undefined;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const wordingId = useId();
  const codeId = useId();
  const headingId = useId();
  const categoryId = useId();

  const [wording, setWording] = useState("");
  const [lenderCode, setLenderCode] = useState("");
  const [bucketKind, setBucketKind] = useState<BucketKind>("prior_to_docs");
  const [category, setCategory] = useState("");
  const add = useAddCondition(fileId);

  function reset() {
    setWording("");
    setLenderCode("");
    setBucketKind("prior_to_docs");
    setCategory("");
  }

  function submit() {
    add.mutate(
      {
        verbatim_text: wording.trim(),
        lender_code: lenderCode.trim() || null,
        lender_category: category.trim() || null,
        bucket_kind: bucketKind,
        // ⚠️ EXPLICITLY `null`, NOT OMITTED, MATCHING THE TWO FIELDS ABOVE. They send `|| null` with
        // a comment saying why — the column is nullable and `""` would be a value the lender never
        // wrote — and a third field escaping that convention in the same expression is the
        // inconsistency worth avoiding. `null` says we considered it and have nothing; leaving the
        // key out says nothing at all. The server turns it into `""` either way.
        bucket_heading: null,
        // ⚠️ AND SENDING A REAL ONE WAS A DEFECT (LP-909 review). It used to send
        // `BUCKET_KIND_LABEL[bucketKind]` — OUR prose — into a column that holds the LENDER's
        // printed vocabulary ("Prior To Docs (PTD)", "Underwriter To Obtain And Clear").
        // `create_manual_condition` refuses to manufacture one for exactly that reason and writes
        // `""` when none is given, meaning "the processor filed it under no heading". The client
        // handing it a label defeated a rule the server states in words.
        //
        // The `unknown` case shows the shape worst: its label is "No heading given", so choosing
        // *no heading* would have written that SENTENCE into the column whose empty value already
        // means it — two rows indistinguishable downstream, only one of them true.
        //
        // The two are different facts, which is why they are different columns: `bucket_kind` is
        // WHEN the condition is due, `bucket_heading` is WHAT THE LENDER PRINTED. Deriving the
        // second from the first is a category error. A typed heading, if ever wanted, needs its own
        // free-text field asking for the lender's heading rather than a dropdown of ours.
      },
      {
        onSuccess: () => {
          notifySuccess({
            title: "Condition added",
            consequence: "It is on the file's list, in the heading you chose.",
          });
          reset();
          onOpenChange(false);
        },
        onError: (error) =>
          notifyError({
            title: "That condition could not be added",
            whatToDo: getErrorMessage(error),
          }),
      },
    );
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        onOpenChange(next);
        if (!next) reset();
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add a condition</DialogTitle>
          <DialogDescription>{roundSentence(rounds)}</DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          <div className="space-y-1.5">
            <Label htmlFor={wordingId}>Lender&rsquo;s wording</Label>
            <Textarea
              id={wordingId}
              value={wording}
              onChange={(event) => setWording(event.target.value)}
              className="min-h-[7rem] font-serif"
            />
            <p className="text-xs text-muted-foreground">Type it exactly as the lender wrote it.</p>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor={codeId}>Lender code</Label>
              {/* Mono, by design rule 2: a code is an identifier printed on a document. */}
              <Input
                id={codeId}
                value={lenderCode}
                placeholder="Optional"
                onChange={(event) => setLenderCode(event.target.value)}
                className="font-mono"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor={categoryId}>Category</Label>
              <Input
                id={categoryId}
                value={category}
                placeholder="Optional"
                onChange={(event) => setCategory(event.target.value)}
              />
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor={headingId}>Heading</Label>
            <Select
              id={headingId}
              value={bucketKind}
              onChange={(event) => setBucketKind(event.target.value as BucketKind)}
            >
              {HEADINGS.map((kind) => (
                <option key={kind} value={kind}>
                  {BUCKET_KIND_LABEL[kind]}
                </option>
              ))}
            </Select>
          </div>
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={add.isPending}>
            Cancel
          </Button>
          <Button onClick={submit} disabled={add.isPending || !wording.trim()}>
            {add.isPending && <Spinner className="mr-2 h-4 w-4" />}
            Add condition
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
