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
    const stamped = document.documentElement.dataset.density as RowDensity | undefined;
    if (stamped) setDensity(stamped);
  }, []);

  // The database is the durable store; if this browser's cookie is stale
  // (changed on another machine), the server's answer wins.
  useEffect(() => {
    const server = preferences?.density;
    if (!server) return;
    if (document.documentElement.dataset.density === server) return;
    applyDensity(server);
    setDensity(server);
  }, [preferences?.density]);

  const choose = useCallback(
    (next: RowDensity) => {
      applyDensity(next);
      setDensity(next);
      // Only the field being changed — sending a stale thoroughness back is how
      // the other preference silently reverts.
      updatePreferences.mutate({ density: next });
    },
    [updatePreferences],
  );

  return { density, choose };
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
