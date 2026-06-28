"use client";

import { DtiCalculator } from "@/components/file/dti/dti-calculator";
import { LtvCalculator } from "@/components/file/ltv/ltv-calculator";
import { OverviewPlaceholder } from "@/components/file/overview/overview-placeholder";
import { ShieldCheck } from "lucide-react";
import { useParams } from "next/navigation";

/**
 * Verification tab (Phase 3). The DTI (LP-76) and LTV (LP-77) calculators are the
 * headline surfaces here; the full findings/resolution UI (LP-81) lands alongside.
 */
export default function VerificationPage() {
  const { id } = useParams<{ id: string }>();

  return (
    <div className="space-y-6">
      <div className="grid gap-6 xl:grid-cols-2">
        <DtiCalculator fileId={id} />
        <LtvCalculator fileId={id} />
      </div>

      <OverviewPlaceholder
        title="Findings & resolution"
        phase="Phase 3 (LP-81)"
        description="Red/yellow/green findings across the file's data and documents, and their resolution."
        icon={ShieldCheck}
      />
    </div>
  );
}
