/**
 * User preferences data layer (LP-79, LP-UI-010).
 *
 * Two preferences, both per USER: the default aggression level (the verification
 * thoroughness applied to a file unless a per-file override dials it up/down —
 * setting it never re-runs any AI, it only moves the read-time cutoff) and the
 * row density.
 *
 * Both fields on the wire are optional, so a client changing one never has to
 * send back the other. Sending a stale copy of a value you are not changing is
 * how a preference silently reverts.
 */
import { apiClient } from "@/lib/api/client";
import type { AggressionLevel } from "@/lib/types/verification";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

const API_V1 = "/api/v1";

/** Mirrors the backend `RowDensity`. Compact is the default. */
export type RowDensity = "compact" | "comfortable" | "relaxed";

export const ROW_DENSITIES: RowDensity[] = ["compact", "comfortable", "relaxed"];

export const DENSITY_LABEL: Record<RowDensity, string> = {
  compact: "Compact",
  comfortable: "Comfortable",
  relaxed: "Relaxed",
};

/** The cookie the server reads to stamp `data-density` before first paint. */
export const DENSITY_COOKIE = "ledger-density";

export interface UserPreferences {
  default_aggression_level: AggressionLevel;
  density: RowDensity;
}

export interface UserPreferencesUpdate {
  default_aggression_level?: AggressionLevel;
  density?: RowDensity;
}

export const preferencesQueryKey = ["preferences", "me"] as const;

export async function fetchPreferences(): Promise<UserPreferences> {
  const res = await apiClient.get<UserPreferences>(`${API_V1}/users/me/preferences`);
  return res.data;
}

export async function updatePreferences(update: UserPreferencesUpdate): Promise<UserPreferences> {
  const res = await apiClient.put<UserPreferences>(`${API_V1}/users/me/preferences`, update);
  return res.data;
}

export function usePreferences() {
  return useQuery({ queryKey: preferencesQueryKey, queryFn: fetchPreferences });
}

export function useUpdatePreferences() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (update: UserPreferencesUpdate) => updatePreferences(update),
    onSuccess: (prefs) => {
      queryClient.setQueryData(preferencesQueryKey, prefs);
    },
  });
}
