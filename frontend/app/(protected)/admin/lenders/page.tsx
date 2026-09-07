"use client";

/**
 * Lender overlays — the admin list (LP-87, redesigned in LP-UI-025).
 *
 * An overlay is where a lender deviates from the investor default, and it is the
 * highest-leverage thing an admin touches: one change moves every file at that
 * lender. So each row leads with how many rules are overridden and when that last
 * changed — not with contact details, which are what you look up second.
 *
 * A LENDER WITH NO OVERRIDES IS NOT A GAP. It means the agency guideline applies
 * unchanged there, which is a real and reassuring answer, so the row says it in
 * words rather than showing a zero and letting the reader wonder whether the data
 * failed to load.
 */

import { StatusToken } from "@/components/status-token";
import { InlineErrorState } from "@/components/ui/error-state";
import { SkeletonText } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useOverlayLenders } from "@/lib/api/overlay-admin";
import { humanize } from "@/lib/format";
import { useAuthStore } from "@/lib/stores/auth-store";
import type { OverlayLenderSummary } from "@/lib/types/overlay-admin";
import { formatDistanceToNow } from "date-fns";
import Link from "next/link";

function changed(iso: string | null): string {
  // Never edited and edited long ago are different facts, and an em dash for both
  // would merge them.
  if (!iso) return "Never edited";
  try {
    return formatDistanceToNow(new Date(iso), { addSuffix: true });
  } catch {
    return "Never edited";
  }
}

export default function AdminLendersPage() {
  const role = useAuthStore((state) => state.user?.role);
  const { data, isPending, isError, refetch } = useOverlayLenders();

  if (role !== "admin") {
    return (
      <p className="border-t border-border py-6 text-sm text-muted-foreground">
        Lender overlays are available to admins only.
      </p>
    );
  }

  return (
    <section aria-labelledby="lenders-heading" className="space-y-4">
      <header>
        <h2 id="lenders-heading" className="text-label uppercase text-muted-foreground">
          Lender overlays
        </h2>
        <p className="mt-1 max-w-prose text-sm text-muted-foreground">
          Where a lender deviates from the investor default — a tighter DTI cap, a higher reserve
          requirement. One change here moves every file at that lender.
        </p>
      </header>

      {isPending ? (
        <SkeletonText lines={4} />
      ) : isError || !data ? (
        <InlineErrorState message="Couldn't load lenders." onRetry={() => void refetch()} />
      ) : data.length === 0 ? (
        <p className="border-t border-border py-6 text-sm text-muted-foreground">
          No lenders configured for your company yet.
        </p>
      ) : (
        <Table className="table-fixed">
          <TableHeader>
            <TableRow>
              <TableHead className="w-[34%]">Lender</TableHead>
              <TableHead className="w-[26%]">Overlay</TableHead>
              <TableHead className="w-[20%]">Last changed</TableHead>
              <TableHead className="w-[20%]">Programs</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.map((lender) => (
              <LenderRow key={lender.id} lender={lender} />
            ))}
          </TableBody>
        </Table>
      )}
    </section>
  );
}

function LenderRow({ lender }: { lender: OverlayLenderSummary }) {
  const overridden = lender.override_count > 0;
  return (
    <TableRow>
      <TableCell className="py-1.5 align-top">
        <Link
          href={`/admin/lenders/${lender.id}`}
          className="font-medium text-foreground hover:text-primary hover:underline"
        >
          {lender.name}
        </Link>
      </TableCell>

      {/* The overlay, in words. `verified` for none, because "the agency
          guideline applies unchanged" is a good state to be in — not a neutral
          absence and certainly not a warning. */}
      <TableCell className="py-1.5 align-top">
        {overridden ? (
          <span className="text-foreground-2">
            {lender.override_count} rule{lender.override_count === 1 ? "" : "s"} overridden
          </span>
        ) : (
          <StatusToken
            meta={{ tone: "verified", label: "Agency guideline, unchanged" }}
            className="text-sm"
          />
        )}
      </TableCell>

      <TableCell className="py-1.5 align-top text-muted-foreground">
        {changed(lender.last_changed_at)}
      </TableCell>

      <TableCell className="py-1.5 align-top text-muted-foreground">
        {lender.supported_programs.length > 0
          ? lender.supported_programs.map(humanize).join(", ")
          : "None set"}
      </TableCell>
    </TableRow>
  );
}
