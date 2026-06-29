/**
 * User preferences data layer (LP-79) — the user-level verification default.
 *
 * Today this carries the default aggression level (the verification thoroughness
 * applied to a file unless a per-file override dials it up/down). Setting it never
 * re-runs any AI — it only changes the cutoff the read-time filter applies.
 */
import { apiClient } from "@/lib/api/client";
import type { AggressionLevel } from "@/lib/types/verification";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

const API_V1 = "/api/v1";

export interface UserPreferences {
  default_aggression_level: AggressionLevel;
}

export const preferencesQueryKey = ["preferences", "me"] as const;

export async function fetchPreferences(): Promise<UserPreferences> {
  const res = await apiClient.get<UserPreferences>(`${API_V1}/users/me/preferences`);
  return res.data;
}

export async function updatePreferences(
  default_aggression_level: AggressionLevel,
): Promise<UserPreferences> {
  const res = await apiClient.put<UserPreferences>(`${API_V1}/users/me/preferences`, {
    default_aggression_level,
  });
  return res.data;
}

export function usePreferences() {
  return useQuery({ queryKey: preferencesQueryKey, queryFn: fetchPreferences });
}

export function useUpdatePreferences() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (level: AggressionLevel) => updatePreferences(level),
    onSuccess: (prefs) => {
      queryClient.setQueryData(preferencesQueryKey, prefs);
    },
  });
}
