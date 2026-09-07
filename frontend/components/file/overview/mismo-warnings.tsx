"use client";

import { StatusToken } from "@/components/status-token";
import { useStatedFinancials } from "@/lib/api/mismo";
import type { ParseWarning, WarningSubject } from "@/lib/types/stated-financials";

/**
 * What the MISMO import could not read (LP-UI-024).
 *
 * "Imported with 6 fields to review" was a toast, and a toast is gone by the time
 * a processor is looking at the thing it described. The warnings live on the
 * import record, so they outlive the toast — this is where you read them
 * afterwards.
 *
 * Each links to the section it concerns. That is only possible because the parser
 * now records the SUBJECT it was reading when it gave up: matching the sentence
 * here would have been the UI re-deriving something the parser already knew, and
 * would break the first time anyone reworded a message.
 */

/** Subject → where on this page the reader should look. `other` has no section. */
const ANCHOR: Record<WarningSubject, string | null> = {
  borrowers: "#card-borrowers",
  income: "#stated-financials",
  loan: "#card-loan",
  property: "#card-property",
  other: null,
};

export function MismoWarnings({ fileId }: { fileId: string }) {
  const { data } = useStatedFinancials(fileId);
  const warnings = data?.mismo_import?.warnings ?? [];

  // Zero warnings shows NOTHING — not an empty panel. A heading saying a clean
  // import had nothing wrong with it is a permanent reminder of a non-event.
  if (warnings.length === 0) return null;

  return (
    <section aria-labelledby="mismo-warnings-heading">
      <header className="flex flex-wrap items-baseline gap-x-3 pb-2">
        <h2 id="mismo-warnings-heading" className="text-label uppercase text-muted-foreground">
          The import could not read
        </h2>
        <span className="text-xs text-muted-foreground">
          {warnings.length} field{warnings.length === 1 ? "" : "s"} to review
        </span>
      </header>

      <ul className="space-y-1.5">
        {warnings.map((warning) => (
          <Warning key={`${warning.subject}:${warning.message}`} warning={warning} />
        ))}
      </ul>

      {/* The block this panel replaced ended "the file was created — use Edit to
          fill these in", which was dropped as redundant beside a link that goes
          to the field. It is redundant for a warning that HAS one. Every warning
          stored before LP-UI-024 coerces to `other` and gets no link, so on any
          file imported before this change the panel was a list of sentences with
          nothing to do — strictly less useful than the block it replaced. Shown
          only when something on screen actually lacks a destination. */}
      {warnings.some((warning) => ANCHOR[warning.subject] === null) ? (
        <p className="pt-2 text-xs text-muted-foreground">
          Warnings without a link name a section this import could not place. Use Edit on the
          section they describe.
        </p>
      ) : null}
    </section>
  );
}

function Warning({ warning }: { warning: ParseWarning }) {
  const anchor = ANCHOR[warning.subject] ?? null;
  return (
    <li className="flex items-start gap-2 text-sm">
      <StatusToken
        meta={{ tone: "attention", label: "To review" }}
        variant="dot"
        className="mt-0.5 shrink-0"
      />
      <span className="text-foreground-2">
        {warning.message}{" "}
        {anchor ? (
          <a href={anchor} className="whitespace-nowrap text-primary hover:underline">
            Go to {SECTION_LABEL[warning.subject]}
          </a>
        ) : null}
      </span>
    </li>
  );
}

const SECTION_LABEL: Record<WarningSubject, string> = {
  borrowers: "borrowers",
  income: "the application data",
  loan: "the loan",
  property: "the property",
  other: "",
};
