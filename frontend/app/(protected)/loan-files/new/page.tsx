import { IntakeForm } from "@/components/intake/intake-form";
import { ArrowLeft } from "lucide-react";
import Link from "next/link";

/**
 * New loan file intake (LP-32). Renders inside the LP-27 protected shell. The
 * form captures the primary borrower, subject property, loan, and lender; on
 * submit it creates the file (Option A, file-first) and navigates to it.
 */
export default function NewLoanFilePage() {
  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div>
        <Link
          href="/dashboard"
          className="inline-flex items-center gap-1.5 rounded text-sm font-medium text-gray-500 transition-colors hover:text-gray-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to dashboard
        </Link>
        <h1 className="mt-3 text-2xl font-bold tracking-tight text-gray-900">New loan file</h1>
        <p className="mt-1 text-sm text-gray-500">
          Only the borrower&apos;s name is required — fill in what you have; the rest can be added
          on the file later.
        </p>
      </div>

      <IntakeForm />
    </div>
  );
}
