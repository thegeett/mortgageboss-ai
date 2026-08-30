"use client";

import { IntakeForm } from "@/components/intake/intake-form";
import { MismoUpload } from "@/components/intake/mismo-upload";
import { ArrowLeft, PencilLine, Upload } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

/**
 * New loan file (LP-55). MISMO import is the **primary** path — the loan officer
 * sends the application as a MISMO file, so the screen leads with "Upload MISMO";
 * manual entry (the Epic 4 intake form, reused) is the secondary fallback,
 * revealed on demand.
 */
export default function NewLoanFilePage() {
  const [manual, setManual] = useState(false);

  return (
    <div className="mx-auto max-w-3xl space-y-8">
      <div>
        <Link
          href="/dashboard"
          className="inline-flex items-center gap-1.5 rounded text-sm font-medium text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
        >
          <ArrowLeft className="h-4 w-4" />
          Back to dashboard
        </Link>
        <h1 className="mt-3 text-2xl font-semibold tracking-tight text-foreground">
          New loan file
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Import the MISMO file from your loan origination system — or enter the application by
          hand.
        </p>
      </div>

      {manual ? (
        <div className="space-y-5">
          <button
            type="button"
            onClick={() => setManual(false)}
            className="inline-flex items-center gap-1.5 rounded text-sm font-medium text-primary transition-colors hover:text-primary/80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
          >
            <Upload className="h-4 w-4" />
            Upload a MISMO file instead
          </button>
          <IntakeForm />
        </div>
      ) : (
        <div className="space-y-6">
          <MismoUpload />

          {/* Secondary path — clearly subordinate to the MISMO upload. */}
          <div className="flex items-center gap-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            <span className="h-px flex-1 bg-border" />
            or
            <span className="h-px flex-1 bg-border" />
          </div>
          <div className="flex flex-col items-center gap-2 text-center">
            <p className="text-sm text-muted-foreground">Don&apos;t have a MISMO file?</p>
            <button
              type="button"
              onClick={() => setManual(true)}
              className="inline-flex items-center gap-2 rounded-md border border-input bg-card px-4 py-2 text-sm font-medium text-foreground-2 transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
            >
              <PencilLine className="h-4 w-4" />
              Create manually
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
