"use client";

import { CalculatorCard } from "@/components/file/calculators/calculator-card";
import { DtiCalculator } from "@/components/file/dti/dti-calculator";
import { LtvCalculator } from "@/components/file/ltv/ltv-calculator";
import { VerificationPanel } from "@/components/file/verification/verification-panel";
import { useParams } from "next/navigation";

/**
 * Verification tab (LP-81 / LP-87) — the Arc A demo surface, composing Phase 3 into one
 * coherent screen: the DTI (LP-76) + LTV (LP-77) calculators PROMINENT at the top, then the
 * four LP-87 calculators (mortgage insurance, self-employed income, reserves, max loan) —
 * all transparent / auto-populated / overrideable / findings-coupled — then the cross-source
 * panel (the run trigger + staleness, the needs guard, the aggression dial, the findings list).
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

      {/* The LP-87 additional calculators — same transparent/overrideable pattern. */}
      <div className="grid gap-6 xl:grid-cols-2">
        <CalculatorCard fileId={id} calculator="mortgage_insurance" />
        <CalculatorCard fileId={id} calculator="self_employed" />
        <CalculatorCard fileId={id} calculator="reserves" />
        <CalculatorCard fileId={id} calculator="max_loan" />
      </div>

      <VerificationPanel fileId={id} />
    </div>
  );
}
