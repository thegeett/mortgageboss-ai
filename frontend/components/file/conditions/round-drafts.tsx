"use client";

import { useConditionDrafts } from "@/lib/api/conditions";
import { Mail, MessageSquare } from "lucide-react";

/**
 * "Drafts for round 1" (LP-922): a way back to the round's unsent emails once the plan panel has gone.
 *
 * SHOWN ONLY WHILE ONE IS UNSENT. Once every draft is marked sent the list's Next step column carries
 * "· sent 08/28" and this line would only repeat it (S3-12 draws no such line).
 */
export function RoundDrafts({
  fileId,
  onOpenDraft,
}: {
  fileId: string;
  onOpenDraft: (draftId: string) => void;
}) {
  const drafts = useConditionDrafts(fileId);
  const unsent = (drafts.data ?? []).filter((draft) => draft.status === "draft");
  if (unsent.length === 0) return null;
  const round = unsent[0]?.round_number;
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-input bg-card px-3 py-2 text-sm">
      <span className="text-xs font-semibold uppercase tracking-wide text-foreground-2">
        Drafts{round ? ` for round ${round}` : ""}
      </span>
      {unsent.map((draft) => (
        <button
          key={draft.id}
          type="button"
          onClick={() => onOpenDraft(draft.id)}
          className="inline-flex items-center gap-1.5 rounded-md border border-input px-2 py-1 text-xs text-primary hover:bg-muted/60"
        >
          {draft.recipient === "underwriter" ? (
            <MessageSquare className="h-3.5 w-3.5" aria-hidden />
          ) : (
            <Mail className="h-3.5 w-3.5" aria-hidden />
          )}
          {draft.label} · draft
        </button>
      ))}
      <span className="text-xs text-muted-foreground">
        Nothing is sent from the app — open one, send it from your mail, then mark it sent.
      </span>
    </div>
  );
}
