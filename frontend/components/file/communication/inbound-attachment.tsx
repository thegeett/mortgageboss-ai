"use client";

import { Button } from "@/components/ui/button";
import { useAttachmentPreview } from "@/lib/api/inbound";
import type { InboundAttachment } from "@/lib/types/inbound";
import { cn } from "@/lib/utils";
import { FileText, ShieldAlert } from "lucide-react";

/** Bytes, in the units a person reads. */
function humanSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * The thumbnail, or the reason there isn't one.
 *
 * THREE OUTCOMES, AND THEY MEAN THREE DIFFERENT THINGS — the same distinction `EmptyState` draws:
 *
 *   an image       safe, and we rendered it
 *   "no preview"   safe, and the renderer cannot open this type (a HEIC, a TIFF)
 *   the reason     not safe, and the prose says what to ask the borrower for
 *
 * Collapsing the middle two would put a safety warning on an ordinary iPhone photo, and collapsing
 * the first two would tell a processor a quarantined file is merely unrenderable.
 *
 * FETCHED ONLY FOR A SAFE ATTACHMENT. The endpoint refuses the others anyway; not asking means a
 * queue of quarantined mail does not fire a request per card to be told so.
 */
function Thumbnail({
  fileId,
  attachment,
}: {
  fileId: string | null;
  attachment: InboundAttachment;
}) {
  const safe = attachment.safety_state === "safe";
  const { data: url, isPending } = useAttachmentPreview(fileId, attachment.id, safe);

  if (!safe) {
    return (
      <div className="flex h-24 w-20 shrink-0 flex-col items-center justify-center gap-1 rounded border border-warning/40 bg-warning/5 px-1 text-center">
        <ShieldAlert className="h-5 w-5 text-warning" aria-hidden />
        <span className="text-[10px] font-medium uppercase tracking-wide text-warning">
          {attachment.safety_state}
        </span>
      </div>
    );
  }
  if (isPending) {
    return (
      <div className="h-24 w-20 shrink-0 animate-pulse rounded border border-input bg-muted" />
    );
  }
  if (!url) {
    return (
      <div className="flex h-24 w-20 shrink-0 flex-col items-center justify-center gap-1 rounded border border-input bg-muted px-1 text-center">
        <FileText className="h-5 w-5 text-muted-foreground" aria-hidden />
        <span className="text-[10px] text-muted-foreground">No preview</span>
      </div>
    );
  }
  return (
    // The alt text says what the image IS, not what the sender called it: the filename is
    // attacker-controlled and an alt attribute is read aloud.
    <img
      src={url}
      alt="First page of the attachment"
      className="h-24 w-20 shrink-0 rounded border border-input bg-card object-cover"
    />
  );
}

/**
 * One attachment: what it is, whether it is safe, and what a processor can do with it.
 *
 * `filename_original` is rendered AS TEXT. React escapes by default and nothing here bypasses that
 * — there is no `dangerouslySetInnerHTML`, no `title`, and no `href` built from it. It is the one
 * place the sender's own string reaches a screen, deliberately: the normalised form has had exactly
 * what a processor needs to recognise the file removed.
 */
export function InboundAttachmentRow({
  fileId,
  attachment,
  onAccept,
  onAcceptAsCorrespondence,
  onReject,
  onUseAsConditionSheet,
  busy = false,
}: {
  fileId: string | null;
  attachment: InboundAttachment;
  onAccept?: () => void;
  onAcceptAsCorrespondence?: () => void;
  onReject?: () => void;
  /** Turn this attachment into the file's condition sheet (S1-13). PDFs only. */
  onUseAsConditionSheet?: () => void;
  busy?: boolean;
}) {
  const decided = attachment.disposition !== "pending";
  const undecidedAndSafe = attachment.safety_state === "safe" && !decided;
  const canAccept = undecidedAndSafe && Boolean(onAccept);
  // ⚠️ PDFs ONLY, AND THE GATE IS HERE RATHER THAN IN A REFUSAL. `reject_unless_pdf` turns anything
  // else into a 422 at the door, so offering this on a .docx would be a button that reliably fails
  // — the dead-button pattern S1-03 and S1-02 were both corrected for. A lender's letter that
  // arrived as something other than a PDF has to be dealt with as a document, not as a sheet.
  const canUseAsSheet =
    undecidedAndSafe &&
    Boolean(onUseAsConditionSheet) &&
    attachment.sniffed_content_type === "application/pdf";
  const name = attachment.filename_original ?? attachment.filename_normalized;

  return (
    <li className="flex items-start gap-3 rounded-lg border border-input bg-card p-3">
      <Thumbnail fileId={fileId} attachment={attachment} />
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <p className="truncate text-sm font-medium text-foreground">
          {/* An unclaimed message carries no filename at all — that is the redaction, not a file
              with no name, and saying so is more honest than an empty line. */}
          {name ?? <span className="italic text-muted-foreground">Name hidden until claimed</span>}
        </p>
        <p className="text-xs text-muted-foreground">
          {humanSize(attachment.size_bytes)}
          {attachment.sniffed_content_type ? ` · ${attachment.sniffed_content_type}` : null}
          {attachment.nesting_depth > 0
            ? ` · forwarded ${attachment.nesting_depth === 1 ? "once" : `${attachment.nesting_depth} times`}`
            : null}
        </p>
        {attachment.safety_reason ? (
          // WRITTEN BY US, not by the sender — safe to show, and the only thing that makes a refusal
          // actionable. "Quarantined" alone does not distinguish "ask for it without a password"
          // from "ask for the file instead of a zip".
          <p className="text-xs text-warning">{attachment.safety_reason}</p>
        ) : null}
        {decided ? (
          <p className={cn("text-xs font-medium", statusTone(attachment.disposition))}>
            {DISPOSITION_LABEL[attachment.disposition]}
          </p>
        ) : null}
      </div>
      {canAccept || canUseAsSheet ? (
        <div className="flex shrink-0 flex-col gap-1">
          {/* ⚠️ FIRST AND PRIMARY (S1-13), AND THAT ORDERING IS THE DECISION. A lender's approval
              letter is the one attachment a processor is most likely to be looking for, and
              "Accept" would file it as a borrower DOCUMENT — classified against a 166-type taxonomy
              with no bucket for it (ADR-403). Putting the right action first is what stops the
              wrong one being the obvious one. */}
          {canUseAsSheet ? (
            <Button size="sm" onClick={onUseAsConditionSheet} disabled={busy}>
              Use as condition sheet
            </Button>
          ) : null}
          {canAccept ? (
            <>
              <Button
                size="sm"
                // Demoted only when the sheet action is beside it: on a non-PDF this is still the
                // primary thing to do, and greying it there would say the row has no good action.
                variant={canUseAsSheet ? "outline" : "default"}
                onClick={onAccept}
                disabled={busy}
              >
                Accept
              </Button>
              <Button size="sm" variant="ghost" onClick={onAcceptAsCorrespondence} disabled={busy}>
                Correspondence
              </Button>
              <Button size="sm" variant="ghost" onClick={onReject} disabled={busy}>
                Reject
              </Button>
            </>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}

const DISPOSITION_LABEL: Record<string, string> = {
  accepted: "Accepted onto this file",
  correspondence: "Kept as correspondence",
  rejected: "Rejected",
  duplicate: "Already on this file",
  pending: "Awaiting a decision",
};

function statusTone(disposition: string): string {
  if (disposition === "accepted" || disposition === "correspondence") return "text-success";
  if (disposition === "rejected") return "text-muted-foreground";
  return "text-foreground";
}
