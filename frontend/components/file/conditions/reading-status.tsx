"use client";

import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { useReadAgain, useReadingState } from "@/lib/api/conditions";
import { getErrorMessage } from "@/lib/errors/api-error";
import { useState } from "react";

function conditions(count: number): string {
  return `${count} condition${count === 1 ? "" : "s"}`;
}

/**
 * LP-952 — where the reading of the newest round's file stands, above its plan (trial items 4 and 5).
 *
 * After Import nothing on screen said the AI was reading, and a reading that never started (LF-DH8V's
 * round 1, imported before the reading existed) looked the same as one running. This says which, polls
 * while it runs, and offers Read conditions / Read again when nothing is running and conditions are
 * unread. Nothing renders once every condition is read.
 */
export function ReadingStatus({ fileId, roundId }: { fileId: string; roundId: string }) {
  // The hook polls while it runs, and refetches the plan and the conditions when it ends.
  const reading = useReadingState(roundId, fileId);
  const readAgain = useReadAgain(fileId);
  const [error, setError] = useState<string | null>(null);

  const data = reading.data;
  if (!data || data.state === "done") return null;

  const read = (
    <Button
      size="sm"
      variant="outline"
      disabled={readAgain.isPending}
      onClick={() => {
        setError(null);
        readAgain.mutate(roundId, { onError: (err) => setError(getErrorMessage(err)) });
      }}
    >
      {data.state === "failed" ? "Read again" : "Read conditions"}
    </Button>
  );

  let body: React.ReactNode;
  if (data.state === "queued" || data.state === "reading") {
    body = (
      <p className="flex items-center gap-2">
        <Spinner className="h-4 w-4" />
        Reading {conditions(data.unread)}… The plan appears here when it is done.
      </p>
    );
  } else if (data.state === "failed") {
    body = (
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p>
          <span className="font-medium text-foreground">The conditions could not be read.</span>{" "}
          {data.error === "stalled"
            ? "The reading stopped before it finished."
            : data.error === "not_queued"
              ? "The reading could not be started."
              : "The reading failed."}{" "}
          {conditions(data.unread)} still unread.
        </p>
        {read}
      </div>
    );
  } else {
    body = (
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p>
          <span className="font-medium text-foreground">
            {conditions(data.unread)} {data.unread === 1 ? "has" : "have"} not been read.
          </span>{" "}
          Reading them builds the plan and the email drafts.
        </p>
        {read}
      </div>
    );
  }

  return (
    <section
      aria-label="Reading the conditions"
      className="mb-3 rounded-lg border border-input bg-card px-3 py-2 text-sm text-foreground-2"
    >
      {body}
      {error ? <p className="mt-1 text-sm text-destructive">{error}</p> : null}
    </section>
  );
}
