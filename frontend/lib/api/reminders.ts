/**
 * Reminder suggestions (LP-814).
 *
 * IT SUGGESTS AND NEVER SENDS. Spec 4.5 says so, and nothing on this path writes a message or
 * queues one — the endpoints return a list and record what a processor decided about it.
 *
 * COMPUTED ON EVERY READ, so there is nothing to invalidate but the read itself: a snooze changes
 * what the next call returns, not a stored row the UI is mirroring.
 */
import { apiClient } from "@/lib/api/client";
import type { ReminderKind, Suggestion } from "@/lib/types/reminder";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

const API_V1 = "/api/v1";

export const remindersQueryKey = (fileId?: string) =>
  fileId ? (["reminders", fileId] as const) : (["reminders"] as const);

/** Everything worth a nudge across the company. THE ONLY VIEW THAT CAN SURFACE A QUIET FILE — a
 *  per-file read would need somebody to open the file to be told nobody has opened it. */
export function useReminders() {
  return useQuery({
    queryKey: remindersQueryKey(),
    queryFn: async () => (await apiClient.get<Suggestion[]>(`${API_V1}/reminders`)).data,
  });
}

export function useFileReminders(fileId: string) {
  return useQuery({
    queryKey: remindersQueryKey(fileId),
    queryFn: async () =>
      (await apiClient.get<Suggestion[]>(`${API_V1}/loan-files/${fileId}/reminders`)).data,
    enabled: Boolean(fileId),
  });
}

export interface SnoozeInput {
  kind: ReminderKind;
  subject_id: string | null;
  /** null DISMISSES. "Come back on Thursday" and "stop telling me" are one decision at two
   *  distances, which is why the absence of a date means something rather than being incomplete. */
  until: string | null;
}

/** Both lists change: a file-level snooze removes a card from the company view too. */
function invalidate(queryClient: ReturnType<typeof useQueryClient>, fileId: string) {
  void queryClient.invalidateQueries({ queryKey: remindersQueryKey() });
  void queryClient.invalidateQueries({ queryKey: remindersQueryKey(fileId) });
}

export function useSnooze(fileId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: SnoozeInput) => {
      await apiClient.post(`${API_V1}/loan-files/${fileId}/reminders/snooze`, input);
    },
    onSuccess: () => invalidate(queryClient, fileId),
  });
}

export function useUnsnooze(fileId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: { kind: ReminderKind; subject_id: string | null }) => {
      await apiClient.post(`${API_V1}/loan-files/${fileId}/reminders/unsnooze`, input);
    },
    onSuccess: () => invalidate(queryClient, fileId),
  });
}
