"use client";

import { DtiCalculator } from "@/components/file/dti/dti-calculator";
import { OverviewPlaceholder } from "@/components/file/overview/overview-placeholder";
import { Gauge, ShieldCheck } from "lucide-react";
import { useParams } from "next/navigation";

/**
 * Verification tab (Phase 3). The DTI calculator (LP-76) is the headline surface
 * here; the LTV calculator (LP-77) and the full findings/resolution UI (LP-81)
 * land alongside it.
 */
export default function VerificationPage() {
  const { id } = useParams<{ id: string }>();

  return (
    <div className="space-y-6">
      <DtiCalculator fileId={id} />

      <div className="grid gap-4 lg:grid-cols-2">
        <OverviewPlaceholder
          title="LTV calculator"
          phase="Phase 3 (LP-77)"
          description="Loan-to-value — the loan amount against the property value, with the same transparent breakdown."
          icon={Gauge}
        />
        <OverviewPlaceholder
          title="Findings & resolution"
          phase="Phase 3 (LP-81)"
          description="Red/yellow/green findings across the file's data and documents, and their resolution."
          icon={ShieldCheck}
        />
      </div>
    </div>
  );
}
