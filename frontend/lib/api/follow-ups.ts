/**
 * LP-1014 — automatic follow-ups (LP-1013's API): the file's list, and the five actions on one email.
 *
 * EVERY ACTION REFRESHES THREE THINGS: the list (status, next date, the pill), the email it acts on
 * (its follow-up bar), and the timeline (Send now adds a row; the pills read the list).
 */
import { apiClient } from "@/lib/api/client";
import { followUpsQueryKey, messageQueryKey } from "@/lib/api/communications";
import { invalidateDraftViews } from "@/lib/api/draft-views";
import type { FollowUp, FollowUpRow } from "@/lib/types/communication";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

const API_V1 = "/api/v1";

export { followUpsQueryKey };

/** The file's emails whose follow-up was ever started, newest first. */
export function useFollowUps(fileId: string) {
  return useQuery({
    queryKey: followUpsQueryKey(fileId),
    queryFn: async () =>
      (await apiClient.get<FollowUpRow[]>(`${API_V1}/loan-files/${fileId}/follow-ups`)).data,
    enabled: Boolean(fileId),
  });
}

/** The three settings a person picks; `tz` is added for Start and Send (the browser's zone). */
export interface FollowUpSettings {
  interval_days: number;
  max_auto: number;
  /** `HH:MM`. */
  time: string;
}

export type FollowUpAction =
  | { kind: "start"; settings: FollowUpSettings; tz: string }
  | { kind: "edit"; settings: FollowUpSettings }
  | { kind: "stop" }
  | { kind: "resume" }
  | { kind: "send-now" };

function request(base: string, action: FollowUpAction) {
  switch (action.kind) {
    case "start":
      return apiClient.post<FollowUp>(`${base}/follow-up/start`, {
        ...action.settings,
        tz: action.tz,
      });
    case "edit":
      return apiClient.patch<FollowUp>(`${base}/follow-up`, action.settings);
    case "stop":
      return apiClient.post<FollowUp>(`${base}/follow-up/stop`);
    case "resume":
      return apiClient.post<FollowUp>(`${base}/follow-up/resume`);
    case "send-now":
      return apiClient.post<FollowUp>(`${base}/follow-up/send-now`);
  }
}

/** One of the five actions on the follow-up of email `communicationId`. */
export function useFollowUpAction(fileId: string, communicationId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (action: FollowUpAction) =>
      (await request(`${API_V1}/loan-files/${fileId}/messages/${communicationId}`, action)).data,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: followUpsQueryKey(fileId) });
      void queryClient.invalidateQueries({ queryKey: messageQueryKey(fileId, communicationId) });
      invalidateDraftViews(queryClient, fileId);
    },
  });
}
