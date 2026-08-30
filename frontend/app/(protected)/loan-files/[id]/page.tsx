"use client";

import { NeedsSummary } from "@/components/file/needs/needs-summary";
import { ActivityFeed } from "@/components/file/overview/activity-feed";
import { BorrowerCard, LoanCard, PropertyCard } from "@/components/file/overview/overview-cards";
import { ReconciliationLedger } from "@/components/file/overview/reconciliation-ledger";
import { StatedFinancialsSection } from "@/components/file/overview/stated-financials-section";
import { useLoanFile, useLoanFileActivity, useLoanFileBorrowers } from "@/lib/api/loan-files";
import { useParams } from "next/navigation";

/**
 * Overview tab (LP-34) — the at-a-glance file summary. Composes the file detail
 * (cached by the layout's `useLoanFile`) with the borrowers/needs/activity reads.
 * Each section handles its own loading / empty / error state, so a sparse DRAFT
 * file degrades gracefully rather than erroring.
 *
 * LP-UI-018 put the reconciliation ledger at the top, because the comparison it
 * draws is what this product is for. It also removed the two "coming in Phase N"
 * placeholder cards: the DTI and LTV they promised are on screen already, pinned
 * in the file context rail by LP-UI-009, so the cards were advertising a feature
 * the processor could see from where they were standing.
 */
export default function OverviewPage() {
  const { id } = useParams<{ id: string }>();
  const file = useLoanFile(id);
  const borrowers = useLoanFileBorrowers(id);
  const activity = useLoanFileActivity(id);

  return (
    <div className="space-y-6">
      <ReconciliationLedger fileId={id} />

      <div className="grid gap-4 lg:grid-cols-3">
        <BorrowerCard
          borrowers={borrowers.data}
          isPending={borrowers.isPending}
          isError={borrowers.isError}
          onRetry={() => void borrowers.refetch()}
        />
        <PropertyCard
          file={file.data}
          isPending={file.isPending}
          isError={file.isError}
          onRetry={() => void file.refetch()}
        />
        <LoanCard
          file={file.data}
          isPending={file.isPending}
          isError={file.isError}
          onRetry={() => void file.refetch()}
        />
      </div>

      {/* The data MISMO import populated (LP-55) — hidden for files without it. */}
      <StatedFinancialsSection fileId={id} />

      {/* The full list is its own route now (LP-UI-022); this is how much is
          outstanding, and the way through. */}
      <NeedsSummary fileId={id} />

      <ActivityFeed
        activity={activity.data}
        isPending={activity.isPending}
        isError={activity.isError}
        onRetry={() => void activity.refetch()}
      />
    </div>
  );
}
