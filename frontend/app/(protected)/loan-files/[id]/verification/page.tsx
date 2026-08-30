"use client";

import { VerificationPanel } from "@/components/file/verification/verification-panel";
import { useParams } from "next/navigation";

/**
 * Verification tab (LP-88) — the full Wireframe-5 production surface, composing all of
 * Phase 3 into one scannable screen. EXTENDS LP-81's tab: the six calculators (LP-76/77/87)
 * via progressive disclosure (a summary strip, expand one for the math), then the
 * verification panel — now with the stats row, the severity/category filter pills (composing
 * with the dial), the run-history version selector, and the full per-finding action set
 * (Apply / Override / Note / Accept-risk / Request-docs), program- and lender-specific.
 * Complexity managed by hierarchy + progressive disclosure so it stays usable day-to-day.
 */
export default function VerificationPage() {
  const { id } = useParams<{ id: string }>();

  return (
    // The panel renders the calculators itself, between the run controls and the
    // outcomes (LP-UI-046). Rendering them here put the run controls and the
    // thoroughness dial below the fold.
    <VerificationPanel fileId={id} />
  );
}
