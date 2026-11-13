"use client";

import { AuditTable } from "@/components/admin/audit-table";
import { usePeople } from "@/lib/api/users";
import { useCan } from "@/lib/auth/permissions";

/**
 * Audit log (LP-MB-Admin-03, mockup 12). Needs `audit.view`, checked here as well as by the admin
 * layout: the layout's key is `users.manage`, and this page's API checks its own.
 */
export default function AuditLogPage() {
  const canView = useCan("audit.view");
  const people = usePeople();

  if (!canView) {
    return (
      <p className="text-sm text-muted-foreground">The audit log is available to admins only.</p>
    );
  }

  return (
    <section aria-labelledby="audit-heading" className="space-y-4">
      <header className="space-y-1">
        <h2 id="audit-heading" className="text-label uppercase text-muted-foreground">
          Audit log
        </h2>
        <p className="max-w-prose text-sm text-muted-foreground">
          Every change made in Administration, newest first: who, what, and the values before and
          after. Read-only; nothing here can be edited or removed. Changes to a loan file are in
          that file&rsquo;s own timeline, not here.
        </p>
      </header>
      <AuditTable people={people.data ?? []} />
    </section>
  );
}
