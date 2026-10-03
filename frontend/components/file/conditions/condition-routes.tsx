"use client";

import { useChooseRoute } from "@/lib/api/conditions";
import { getErrorMessage } from "@/lib/errors/api-error";
import type { Condition } from "@/lib/types/conditions";
import { cn } from "@/lib/utils";
import { useState } from "react";

/**
 * LP-955 — how this condition gets done at its lender, when the lender has more than one way (IV-01 at
 * UWM: "Pulled in UWM's system" asks the underwriter to clear it; "Our vendor" keeps it her task to
 * upload the vendor's invoice). Renders nothing for the conditions no route is defined for.
 */
export function ConditionRoutes({ fileId, condition }: { fileId: string; condition: Condition }) {
  const choose = useChooseRoute(fileId);
  const [error, setError] = useState<string | null>(null);
  if (!condition.routes || condition.routes.length === 0) return null;
  return (
    <section
      aria-label="How this gets done"
      className="flex flex-col gap-2 rounded-lg border border-input bg-card p-3"
    >
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
        How this gets done
      </p>
      <div className="grid gap-2 sm:grid-cols-2">
        {condition.routes.map((route) => {
          const chosen = condition.chosen_route === route.key;
          return (
            <button
              key={route.key}
              type="button"
              aria-pressed={chosen}
              disabled={choose.isPending}
              onClick={() => {
                setError(null);
                choose.mutate(
                  { conditionId: condition.id, route: route.key },
                  { onError: (err) => setError(getErrorMessage(err)) },
                );
              }}
              className={cn(
                "flex flex-col items-start gap-0.5 rounded-md border p-2 text-left",
                chosen ? "border-primary bg-primary/5" : "border-input",
              )}
            >
              <span className="text-sm font-medium text-foreground">{route.label}</span>
              <span className="text-xs text-foreground-2">{route.hint}</span>
            </button>
          );
        })}
      </div>
      {error ? <p className="text-xs text-destructive">{error}</p> : null}
    </section>
  );
}
