"use client";

import { ActivityFeed } from "@/components/file/overview/activity-feed";
import { NeedsSection } from "@/components/file/overview/needs-section";
import { BorrowerCard, LoanCard, PropertyCard } from "@/components/file/overview/overview-cards";
import { OverviewPlaceholder } from "@/components/file/overview/overview-placeholder";
import {
  useLoanFile,
  useLoanFileActivity,
  useLoanFileBorrowers,
  useLoanFileNeeds,
} from "@/lib/api/loan-files";
import { Gauge, Sparkles } from "lucide-react";
import { useParams } from "next/navigation";

/**
 * Overview tab (LP-34) — the at-a-glance file summary. Composes the file detail
 * (cached by the layout's `useLoanFile`) with the borrowers/needs/activity reads.
 * Each section handles its own loading / empty / error state, so a sparse DRAFT
 * file degrades gracefully rather than erroring.
 */
export default function OverviewPage() {
  const { id } = useParams<{ id: string }>();
  const file = useLoanFile(id);
  const borrowers = useLoanFileBorrowers(id);
  const needs = useLoanFileNeeds(id);
  const activity = useLoanFileActivity(id);

  return (
    <div className="space-y-6">
      <div className="grid gap-4 lg:grid-cols-3">
        <BorrowerCard
          borrowers={borrowers.data}
          isPending={borrowers.isPending}
          isError={borrowers.isError}
        />
        <PropertyCard file={file.data} isPending={file.isPending} isError={file.isError} />
        <LoanCard file={file.data} isPending={file.isPending} isError={file.isError} />
      </div>

      <NeedsSection needs={needs.data} isPending={needs.isPending} isError={needs.isError} />

      <div className="grid gap-4 lg:grid-cols-2">
        <ActivityFeed
          activity={activity.data}
          isPending={activity.isPending}
          isError={activity.isError}
        />
        <div className="space-y-4">
          <OverviewPlaceholder
            title="AI summary"
            phase="Phase 6"
            description="A generated plain-language summary of this file's status and what's outstanding."
            icon={Sparkles}
          />
          <OverviewPlaceholder
            title="Key metrics (DTI / LTV)"
            phase="Phase 3"
            description="Calculated ratios — debt-to-income, loan-to-value — surfaced once verification lands."
            icon={Gauge}
          />
        </div>
      </div>
    </div>
  );
}
