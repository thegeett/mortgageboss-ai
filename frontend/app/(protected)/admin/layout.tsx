"use client";

import { useCan } from "@/lib/auth/permissions";

/**
 * The gate for every page under /admin (LP-MB-Admin-02).
 *
 * Checked once here, by permission key, instead of a role check copied into each page.
 * `users.manage` is the key the Administration nav item uses, so the link and the pages
 * agree about who gets in. UX only: each admin API route checks its own key.
 */
export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const canAdminister = useCan("users.manage");

  if (!canAdminister) {
    return (
      <section className="space-y-2">
        <h2 className="text-label uppercase text-muted-foreground">Administration</h2>
        <p className="text-sm text-muted-foreground">Administration is available to admins only.</p>
      </section>
    );
  }

  return <>{children}</>;
}
