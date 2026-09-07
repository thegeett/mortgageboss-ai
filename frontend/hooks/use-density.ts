"use client";

import {
  DENSITY_COOKIE,
  type RowDensity,
  usePreferences,
  useUpdatePreferences,
} from "@/lib/api/preferences";
import { useCallback, useEffect, useState } from "react";

const DEFAULT_DENSITY: RowDensity = "compact";

/**
 * Row density (LP-UI-010), on the same two-part pattern as ⌘B in LP-UI-008 —
 * for the same reason and with one addition.
 *
 * `data-density` on `<html>` is the single source of truth for what is on
 * screen: `--row-h` and `--row-px` hang off it, and every dense surface reads
 * those. The server stamps it from a cookie, so the first paint is already at
 * the right density and nothing reflows on hydration.
 *
 * The DURABLE store is the user row in the database, not the cookie. Density is
 * a per-person ergonomic preference, so it has to follow the person to another
 * machine; the cookie is only the fast path that makes the server render right.
 * The two can disagree — a preference changed on another device — so this hook
 * reconciles the cookie to the server's answer once the query resolves.
 */
export function useDensity() {
  const { data: preferences } = usePreferences();
  const updatePreferences = useUpdatePreferences();
  const [density, setDensity] = useState<RowDensity>(DEFAULT_DENSITY);

  // Adopt whatever the server already stamped, without changing it.
  useEffect(() => {
    setDensity(currentDensity());
  }, []);

  // The database is the durable store; if this browser's cookie is stale
  // (changed on another machine), the server's answer wins.
  const reconciling = updatePreferences.isPending;
  useEffect(() => {
    // Never while our own write is in flight. A background refetch (window
    // focus, say) resolving mid-PUT carries the value we are replacing, and
    // reconciling to it would snap the whole UI back to the old density and
    // then forward again when the PUT lands.
    if (reconciling) return;
    const server = preferences?.density;
    if (!server) return;
    if (currentDensity() === server) return;
    applyDensity(server);
    setDensity(server);
  }, [preferences?.density, reconciling]);

  const choose = useCallback(
    (next: RowDensity) => {
      // Re-picking the density you are already on is not a change. Without this
      // the menu fired a PUT per click. `pickLevel` in VerificationPanel already
      // guards its own dial the same way.
      if (next === currentDensity()) return;
      const previous = currentDensity();
      applyDensity(next);
      setDensity(next);
      // Only the field being changed — sending a stale thoroughness back is how
      // the other preference silently reverts.
      updatePreferences.mutate(
        { density: next },
        {
          // The DOM was changed optimistically, so a failed PUT leaves the
          // screen claiming a preference the database does not hold. Left alone
          // it "worked" and then silently reverted on some later load, when the
          // reconcile above pulled the server's older answer. Snapping back now
          // is the honest version of the same outcome.
          onError: () => {
            applyDensity(previous);
            setDensity(previous);
          },
        },
      );
    },
    [updatePreferences],
  );

  return { density, choose };
}

/**
 * What is on screen right now, read from the attribute that decides it.
 *
 * The attribute is the source of truth (the CSS hangs off it), so every decision
 * here reads it rather than the React mirror — which starts at the default and
 * only catches up in an effect, and would answer "compact" for a relaxed user on
 * the first render.
 */
function currentDensity(): RowDensity {
  const stamped = document.documentElement.dataset.density;
  return stamped === "comfortable" || stamped === "relaxed" ? stamped : DEFAULT_DENSITY;
}

/** Write the attribute the CSS reads, and the cookie the server reads next time. */
function applyDensity(next: RowDensity) {
  const root = document.documentElement;
  if (next === DEFAULT_DENSITY) root.removeAttribute("data-density");
  else root.dataset.density = next;
  // Compact is the default and the server tests for the other two, so compact
  // deletes the cookie rather than writing a second spelling of "no cookie".
  document.cookie =
    next === DEFAULT_DENSITY
      ? `${DENSITY_COOKIE}=;path=/;max-age=0;samesite=lax`
      : `${DENSITY_COOKIE}=${next};path=/;max-age=31536000;samesite=lax`;
}
