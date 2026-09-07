"use client";

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

import { MailboxConnections } from "@/components/admin/mailbox-connections";
import { useAuthStore } from "@/lib/stores/auth-store";

export default function AdminEmailPage() {
  const role = useAuthStore((state) => state.user?.role);

  if (role !== "admin") {
    return (
      <section className="space-y-2">
        <h2 className="text-label uppercase text-muted-foreground">Email</h2>
        <p className="text-sm text-muted-foreground">
          Connecting a mailbox is available to admins only.
        </p>
      </section>
    );
  }

  return (
    <div className="space-y-6">
      <header className="space-y-1">
        <h1 className="text-lg font-semibold text-foreground">Email</h1>
        <p className="text-sm text-muted-foreground">
          How your borrowers&apos; mail reaches this system.
        </p>
      </header>
      <MailboxConnections />
    </div>
  );
}
