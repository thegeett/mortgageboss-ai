import { useCapabilities } from "@/lib/api/capabilities";
import { messageTimeFull } from "@/lib/message-time";
import type { DocumentEmailOrigin } from "@/lib/types/document";
import { Mail } from "lucide-react";
import Link from "next/link";

/** LP-1009 — where an accepted email attachment came from. The sender's address is shown as text. */
export function emailOriginLabel(origin: DocumentEmailOrigin): string {
  const sender = origin.from_address ?? "unknown sender";
  return `Email · from ${sender} · ${messageTimeFull(origin.received_at)}`;
}

/**
 * The label, linking to the email on the file's Communication tab. Plain text when that tab shows no
 * emails (`inbox` off, or not known yet), because the link would land on nothing.
 */
export function EmailOriginLink({
  fileId,
  origin,
}: {
  fileId: string;
  origin: DocumentEmailOrigin;
}) {
  const { data: capabilities } = useCapabilities();
  if (!capabilities?.inbox) {
    return (
      <span className="mt-0.5 flex items-center gap-1 truncate text-xs text-muted-foreground">
        <Mail className="h-3 w-3 shrink-0" aria-hidden />
        <span className="truncate">{emailOriginLabel(origin)}</span>
      </span>
    );
  }
  return (
    <Link
      href={`/loan-files/${fileId}/communication#email-${origin.inbound_message_id}`}
      // Inside a row that opens the document: the link is its own action.
      onClick={(event) => event.stopPropagation()}
      onKeyDown={(event) => event.stopPropagation()}
      className="mt-0.5 flex items-center gap-1 truncate text-xs text-muted-foreground underline-offset-2 hover:underline"
    >
      <Mail className="h-3 w-3 shrink-0" aria-hidden />
      <span className="truncate">{emailOriginLabel(origin)}</span>
    </Link>
  );
}
