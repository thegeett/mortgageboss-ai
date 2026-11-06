/**
 * Administration → Email (LP-808).
 *
 * The one screen where a company connects its own mail. Admin-gated in the UI for the same reason
 * the endpoints are: creating a connection mints an address that accepts mail into every one of
 * this company's loan files.
 *
 * Reading them is NOT gated on the server — the staleness signal is for the processor whose
 * documents stopped arriving — but this page is administration, so the gate here matches the page
 * rather than the endpoint.
 */

import { notFound } from "next/navigation";

/**
 * LP-1011 — HIDDEN. Route B (connecting a company mailbox) is superseded by
 * docs/email-communication/loan-email.md: borrowers reply to each file's own address. The screen
 * answers 404 and is off the Administration menu; `MailboxConnections` and the API stay.
 */
export default function AdminEmailPage() {
  notFound();
}
