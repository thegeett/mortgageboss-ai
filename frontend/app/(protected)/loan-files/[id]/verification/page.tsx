"use client";

import { DtiCalculator } from "@/components/file/dti/dti-calculator";
import { LtvCalculator } from "@/components/file/ltv/ltv-calculator";
import { VerificationPanel } from "@/components/file/verification/verification-panel";
import { useParams } from "next/navigation";

/**
 * Verification tab (LP-81) — the Arc A demo surface, composing Phase 3 into one
 * coherent screen: the DTI (LP-76) + LTV (LP-77) calculators PROMINENT at the top
 * (transparent, lender-specific limits via LP-80), then the cross-source panel —
 * the run trigger + staleness, the needs-completeness guard, the aggression dial,
 * and the interactive findings list (resolve / templated wording / source location).
 */
export default function VerificationPage() {
  const { id } = useParams<{ id: string }>();

  return (
    <div className="space-y-6">
      {/* The headline "replace ChatGPT" win — transparent DTI/LTV, prominent. */}
      <div className="grid gap-6 xl:grid-cols-2">
        <DtiCalculator fileId={id} />
        <LtvCalculator fileId={id} />
      </div>

      <VerificationPanel fileId={id} />
    </div>
  );
}
