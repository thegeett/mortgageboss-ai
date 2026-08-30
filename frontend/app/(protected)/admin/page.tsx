"use client";

import { useOverlayLenders } from "@/lib/api/overlay-admin";
import { useAuthStore } from "@/lib/stores/auth-store";
import { formatDistanceToNow } from "date-fns";
import Link from "next/link";

/**
 * Administration (LP-27, made real in LP-UI-025).
 *
 * This was a "user management is coming" panel with two links that the context
 * column already lists. What an admin actually wants on arriving is the state of
 * what they configure — and the one configurable thing that moves loan files is
 * the overlays.
 *
 * The counts come from the lenders list this page links to, on the same query key,
 * so opening Lenders next costs no request and the two screens cannot disagree
 * about how many lenders have an overlay.
 *
 * Role gating here is UX only; the backend is the authorization boundary (LP-24).
 */
export default function AdminPage() {
  const role = useAuthStore((state) => state.user?.role);
  const isAdmin = role === "admin";
  const { data, isPending, isError } = useOverlayLenders();

  if (!isAdmin) {
    return (
      <section className="space-y-2">
        <h2 className="text-label uppercase text-muted-foreground">Administration</h2>
        <p className="text-sm text-muted-foreground">Administration is available to admins only.</p>
      </section>
    );
  }

  const lenders = data ?? [];
  const withOverlay = lenders.filter((lender) => lender.override_count > 0);
  const overridden = withOverlay.reduce((sum, lender) => sum + lender.override_count, 0);
  const lastChange = lenders
    .map((lender) => lender.last_changed_at)
    .filter((at): at is string => at !== null)
    .sort()
    .at(-1);

  return (
    <div className="space-y-6">
      <section aria-labelledby="admin-overlays-heading" className="space-y-3">
        <header className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
          <h2 id="admin-overlays-heading" className="text-label uppercase text-muted-foreground">
            Lender overlays
          </h2>
          <Link
            href="/admin/lenders"
            className="text-xs text-muted-foreground hover:text-primary hover:underline"
          >
            Open lender overlays
          </Link>
        </header>

        {isPending ? (
          <p className="text-sm text-muted-foreground" aria-busy>
            <output className="sr-only">Loading the overlay summary</output>
            Loading…
          </p>
        ) : isError ? (
          <p className="text-sm text-muted-foreground">The lender list is unavailable.</p>
        ) : lenders.length === 0 ? (
          <p className="max-w-prose text-sm text-muted-foreground">
            No lenders are configured for your company yet.
          </p>
        ) : (
          <>
            <div className="flex flex-wrap items-baseline gap-x-8 gap-y-2">
              <Figure label="Lenders" value={String(lenders.length)} />
              <Figure label="With an overlay" value={String(withOverlay.length)} />
              <Figure label="Rules overridden" value={String(overridden)} />
              <Figure
                label="Last changed"
                value={
                  lastChange
                    ? formatDistanceToNow(new Date(lastChange), { addSuffix: true })
                    : "Never"
                }
              />
            </div>
            {/* Said plainly, because a page of zeroes otherwise reads as a page
                that failed to load. No overlay anywhere means the agency
                guideline applies everywhere, which is a real answer. */}
            {withOverlay.length === 0 ? (
              <p className="max-w-prose text-sm text-muted-foreground">
                No lender deviates from the investor default, so the agency guideline applies
                unchanged on every file.
              </p>
            ) : null}
          </>
        )}
      </section>

      {/* Kept, and kept small. It is still true, and dropping it would leave an
          admin wondering where user management is. */}
      <p className="max-w-prose border-t border-border pt-4 text-xs text-muted-foreground">
        Inviting and managing processors arrives in a later phase — accounts are seed or admin
        provisioned for now.
      </p>
    </div>
  );
}

function Figure({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="tabular text-xl font-medium text-foreground">{value}</p>
      <p className="text-xs text-muted-foreground">{label}</p>
    </div>
  );
}
