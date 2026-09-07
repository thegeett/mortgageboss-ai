"use client";

import { IntakeForm } from "@/components/intake/intake-form";
import { MismoUpload } from "@/components/intake/mismo-upload";

/**
 * New loan file (LP-55, redesigned in LP-UI-023).
 *
 * Two ways in, honestly ranked. The MISMO drop is the primary action because it
 * fills in everything the form below asks for — borrowers, property, loan terms,
 * income, assets and liabilities — and the form is for the files that arrive
 * without one.
 *
 * BOTH ARE ON THE PAGE. Manual entry used to be a toggle that replaced the
 * dropzone, which made the second path look like a different screen and hid the
 * primary one behind a decision the processor had to make before seeing either.
 * Ranking two options is a matter of order and weight, not of concealment.
 *
 * "Back to dashboard" left with the heading: the topbar breadcrumb says
 * "Pipeline / New file" and links back, which is where every other screen in
 * this redesign puts it (LP-UI-016).
 */
export default function NewLoanFilePage() {
  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <MismoUpload />

      <div className="flex items-center gap-3">
        <span className="h-px flex-1 bg-border" />
        <span className="text-label uppercase text-muted-foreground">or start it by hand</span>
        <span className="h-px flex-1 bg-border" />
      </div>

      {/* Said before the form rather than discovered inside it: a sparse file is
          allowed, and knowing that up front is what makes the form approachable
          rather than a wall of blanks. It matches the model — only first and last
          name are required. */}
      <p className="max-w-prose text-sm text-muted-foreground">
        Only the borrower&rsquo;s first and last name are required. A loan file is allowed to start
        sparse — everything else can arrive with the documents.
      </p>

      <IntakeForm />
    </div>
  );
}
