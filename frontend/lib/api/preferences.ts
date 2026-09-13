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

/**
 * Where this processor writes their email (LP-855). Mirrors the backend `MailClient`.
 *
 * NOTHING IN A BROWSER CAN DETECT THIS — there is no API that reports it — so it is asked once, on
 * the first draft, rather than guessed. `mailto` is the safe answer and the fallback: it hands the
 * message to whatever the computer already opens, which is right for Apple Mail, Thunderbird and a
 * locally installed Outlook, and is the only choice that cannot be wrong.
 */
export type MailClient = "gmail" | "outlook_work" | "outlook_personal" | "mailto";

export const MAIL_CLIENTS: MailClient[] = ["gmail", "outlook_work", "outlook_personal", "mailto"];

/** What the button says it will do, before it does it. */
export const MAIL_CLIENT_LABEL: Record<MailClient, string> = {
  gmail: "Gmail",
  outlook_work: "Outlook",
  outlook_personal: "Outlook",
  mailto: "mail app",
};

export interface UserPreferences {
  default_aggression_level: AggressionLevel;
  density: RowDensity;
  /**
   * LP-855 — `null` means NOBODY HAS BEEN ASKED, which is not the same as choosing the desktop
   * default. The picker is shown once on the first draft; a value that could not tell the two
   * apart would show it forever or never.
   */
  mail_client: MailClient | null;
  /** Which option the picker pre-selects, from the caller's own sign-in domain. Never applied. */
  suggested_mail_client: MailClient;
  /** Why, in the picker's own words. Empty when the domain says nothing. */
  mail_client_suggestion_reason: string;
  /**
   * Where this user put the reviewer's two dividers (LP-UI-030), as
   * `[list %, canvas %]`. `null` means never adjusted — the reviewer shows its
   * own default rather than a value nobody chose.
   */
  reviewer_pane_split: [number, number] | null;
}

export interface UserPreferencesUpdate {
  default_aggression_level?: AggressionLevel;
  density?: RowDensity;
  reviewer_pane_split?: [number, number];
  mail_client?: MailClient;
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
