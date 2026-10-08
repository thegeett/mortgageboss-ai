"use client";

import { Button } from "@/components/ui/button";
import { useDeclineFileLender, useFileLender, useSetFileLender } from "@/lib/api/conditions";
import { getErrorMessage } from "@/lib/errors/api-error";
import type { LenderSuggestion } from "@/lib/types/conditions";
import Link from "next/link";
import { useState } from "react";

const WHERE: Record<LenderSuggestion["source"], string> = {
  reader: "the sheet’s layout",
  mortgagee_clause: "the sheet’s mortgagee clause",
  header: "the sheet’s header",
};

/**
 * LP-949 — the file's lender, above the conditions, while the file has none.
 *
 * When the newest sheet names a lender it offers that lender, set only when she presses the button,
 * never by itself. LP-965 — NOT ABOUT TYPING ANY MORE: a condition's library type comes from its
 * reading, fresh every time, not from the lender's codes (ADR-419). The lender still decides how a
 * condition gets done there (who orders what), so a file without one is still worth flagging.
 */
export function FileLenderBanner({ fileId }: { fileId: string }) {
  const lender = useFileLender(fileId);
  const set = useSetFileLender(fileId);
  const decline = useDeclineFileLender(fileId);
  const [error, setError] = useState<string | null>(null);

  const data = lender.data;
  if (!data) return null;
  if (data.lender) return null;

  const overview = `/loan-files/${fileId}`;
  const pending = set.isPending || decline.isPending;

  let body: React.ReactNode;
  if (data.suggestion) {
    const suggestion = data.suggestion;
    body = (
      <div className="flex flex-col gap-2">
        <p>
          <span className="font-medium text-foreground">This file has no lender.</span> The sheet
          looks like <span className="font-medium text-foreground">{suggestion.name}</span> (from{" "}
          {WHERE[suggestion.source]}). Set it as this file’s lender?
          {suggestion.lender_exists
            ? ""
            : ` Setting it also adds ${suggestion.name} to your lenders.`}
        </p>
        <div className="flex flex-wrap gap-2">
          <Button
            size="sm"
            disabled={pending}
            onClick={() => {
              setError(null);
              set.mutate(
                { lender_key: suggestion.key },
                { onError: (err) => setError(getErrorMessage(err)) },
              );
            }}
          >
            Set {suggestion.name} as the lender
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={pending}
            onClick={() => {
              setError(null);
              decline.mutate(suggestion.round_id, {
                onError: (err) => setError(getErrorMessage(err)),
              });
            }}
          >
            Not this lender
          </Button>
        </div>
      </div>
    );
  } else {
    body = (
      <p>
        <span className="font-medium text-foreground">This file has no lender</span>, so the
        lender’s own way of doing each condition can’t be used. Set the lender in{" "}
        <Link
          href={overview}
          className="font-medium text-primary underline-offset-2 hover:underline"
        >
          Overview
        </Link>
        .
      </p>
    );
  }

  return (
    <section
      aria-label="The file’s lender"
      className="mb-3 rounded-lg border border-warning/50 bg-warning/5 px-3 py-2 text-sm text-foreground-2"
    >
      {body}
      {error ? <p className="mt-1 text-sm text-destructive">{error}</p> : null}
    </section>
  );
}
