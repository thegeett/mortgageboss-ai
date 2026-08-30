"use client";

/**
 * Lender overlays — admin list (LP-87). The company's lenders, each editable for its overlay
 * (the per-lender deviations from the investor default). Admin-only (the nav + backend gate it).
 */

import { InlineErrorState } from "@/components/ui/error-state";
import { SkeletonText } from "@/components/ui/skeleton";
import { useOverlayLenders } from "@/lib/api/overlay-admin";
import { useAuthStore } from "@/lib/stores/auth-store";
import { ChevronRight, SlidersHorizontal } from "lucide-react";
import Link from "next/link";

export default function AdminLendersPage() {
  const role = useAuthStore((state) => state.user?.role);
  const { data, isPending, isError, refetch } = useOverlayLenders();

  if (role !== "admin") {
    return (
      <div className="rounded-lg border border-dashed border-input bg-white px-6 py-16 text-center text-sm text-muted-foreground">
        Lender overlays are available to admins only.
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="flex items-center gap-2 text-2xl font-semibold tracking-tight text-foreground">
          <SlidersHorizontal className="h-6 w-6 text-primary" />
          Lender overlays
        </h2>
        <p className="mt-1 text-muted-foreground">
          A lender overlay is where a lender deviates from the investor default (e.g. a tighter DTI
          cap). Edit them here — no JSON, with a required reason + an audit trail.
        </p>
      </div>

      {isPending ? (
        <SkeletonText lines={4} />
      ) : isError || !data ? (
        <InlineErrorState message="Couldn't load lenders." onRetry={() => void refetch()} />
      ) : data.length === 0 ? (
        <div className="rounded-lg border border-dashed border-input bg-white px-6 py-12 text-center text-sm text-muted-foreground">
          No lenders configured for your company yet.
        </div>
      ) : (
        <div className="divide-y divide-border rounded-lg border border-border bg-white">
          {data.map((lender) => (
            <Link
              key={lender.id}
              href={`/admin/lenders/${lender.id}`}
              className="flex items-center justify-between gap-3 px-4 py-3 hover:bg-muted"
            >
              <div className="min-w-0">
                <div className="truncate text-sm font-medium text-foreground">{lender.name}</div>
                <div className="text-xs text-muted-foreground">
                  {lender.supported_programs.join(", ") || "no programs set"}
                </div>
              </div>
              <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
