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
 * LP-949 — the file's lender, above the conditions, while it is missing or has no code map.
 *
 * A CONDITION GETS ITS LIBRARY TYPE ONLY FROM ITS LENDER'S CODES, so a file with no lender imports
 * every condition untyped: no library wording in the emails, nothing found already in the file,
 * nothing waiting on anything (the 2026-09-30 staging trial). This says so, and when the newest sheet
 * names a lender it offers that lender — set only when she presses the button, never by itself.
 */
export function FileLenderBanner({ fileId }: { fileId: string }) {
  const lender = useFileLender(fileId);
  const set = useSetFileLender(fileId);
  const decline = useDeclineFileLender(fileId);
  const [error, setError] = useState<string | null>(null);

  const data = lender.data;
  if (!data) return null;
  if (data.lender?.has_code_map) return null;

  const overview = `/loan-files/${fileId}`;
  const pending = set.isPending || decline.isPending;

  let body: React.ReactNode;
  if (data.lender) {
    body = (
      <p>
        <span className="font-medium text-foreground">{data.lender.name}</span> has no condition
        codes in the app, so its conditions can’t be matched to the library. An admin can give its
        codes a meaning in the lender’s settings.
      </p>
    );
  } else if (data.suggestion) {
    const suggestion = data.suggestion;
    body = (
      <div className="flex flex-col gap-2">
        <p>
          <span className="font-medium text-foreground">This file has no lender.</span> The sheet
          looks like <span className="font-medium text-foreground">{suggestion.name}</span> (from{" "}
          {WHERE[suggestion.source]}). Set it as this file’s lender?{" "}
          {suggestion.has_code_map
            ? `Its conditions are then matched to the library${
                suggestion.lender_exists ? "" : `, and ${suggestion.name} is added to your lenders`
              }.`
            : `${suggestion.name} has no condition codes in the app yet, so its conditions are not matched to the library until an admin gives its codes a meaning.`}
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
        <span className="font-medium text-foreground">This file has no lender</span>, so its
        conditions can’t be matched to the library: no document is found already in the file, and no
        condition waits on another. Set the lender in{" "}
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
