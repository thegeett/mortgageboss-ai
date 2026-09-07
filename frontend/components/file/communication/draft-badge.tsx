"use client";

import { useOutboundDraft } from "@/lib/api/communications";
import { FileText } from "lucide-react";
import Link from "next/link";

/**
 * How many documents are waiting in this file's draft email, and the way to it (LP-826).
 *
 * REPORTED: clicking "Request" gave no sign that a draft now existed. LP-809's whole design is that
 * requests ACCUMULATE INTO ONE EMAIL, and that is invisible at the only moment a processor is
 * thinking about it — after a click they cannot tell whether they started an email, added to one
 * that already had two things in it, or asked for something that will not appear in any email.
 *
 * A COUNT, NOT A TOAST. A toast says "that worked" and disappears, which answers a question nobody
 * asked; the useful fact is a running total that persists, because it is what decides whether to
 * keep adding or go and send. It survives a reload and is the same for a colleague looking at the
 * same file, which a notification could never be.
 *
 * DERIVED FROM THE DRAFT'S CONTENTS, never from counting clicks. `needs_item_count` is what the
 * draft actually holds, so removing a line from the email makes this fall — where a click counter
 * would drift the moment anybody edited the draft, and would keep claiming an email contains
 * something it does not.
 *
 * ABSENT RATHER THAN ZERO. `GET /outbound/draft` 404s when there is no open draft, which the hook
 * returns as null. A badge reading "0 documents" would be a claim about an email that does not
 * exist.
 */
export function DraftBadge({ fileId }: { fileId: string }) {
  const { data: draft } = useOutboundDraft(fileId);
  const count = draft?.needs_item_count ?? 0;
  if (count === 0) return null;

  return (
    <Link
      href={`/loan-files/${fileId}/communication`}
      className="inline-flex items-center gap-1.5 rounded-full border border-primary/30 bg-primary/5 px-2.5 py-1 text-xs font-medium text-primary hover:bg-primary/10"
    >
      <FileText className="h-3.5 w-3.5" aria-hidden />
      {count === 1 ? "1 document in the draft" : `${count} documents in the draft`}
    </Link>
  );
}
