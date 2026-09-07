/**
 * Route B connections (LP-808) — the guided flow, and the staleness signal.
 *
 * THERE IS NO ENDPOINT THAT CREATES A ROUTING RULE, and there cannot be: a rule lives in the
 * customer's own admin console, and reaching it would need a restricted Google scope or a Microsoft
 * policy exemption an admin should refuse. So this is guidance plus automatic verification.
 */
import { apiClient } from "@/lib/api/client";
import type { ConnectionSteps, MailboxConnection } from "@/lib/types/mailbox-connection";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

const PATH = "/api/v1/mailbox-connections";

export const connectionsQueryKey = () => ["mailbox-connections"] as const;
export const connectionStepsQueryKey = (id: string) => ["mailbox-connection-steps", id] as const;

export function useMailboxConnections() {
  return useQuery({
    queryKey: connectionsQueryKey(),
    queryFn: async () => (await apiClient.get<MailboxConnection[]>(PATH)).data,
  });
}

export function useConnectionSteps(connectionId: string | null) {
  return useQuery({
    queryKey: connectionStepsQueryKey(connectionId ?? ""),
    queryFn: async () =>
      (await apiClient.get<ConnectionSteps>(`${PATH}/${connectionId}/steps`)).data,
    enabled: Boolean(connectionId),
  });
}

export interface ConnectInput {
  provider: string;
  source_address?: string | null;
}

export function useConnectMailbox() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: ConnectInput) =>
      (await apiClient.post<MailboxConnection>(PATH, input)).data,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: connectionsQueryKey() });
    },
  });
}

export function useEmailSteps(connectionId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (adminEmail: string) =>
      (
        await apiClient.post<MailboxConnection>(`${PATH}/${connectionId}/email-steps`, {
          admin_email: adminEmail,
        })
      ).data,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: connectionsQueryKey() });
    },
  });
}

export function useRevokeConnection() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (connectionId: string) =>
      (await apiClient.delete<MailboxConnection>(`${PATH}/${connectionId}`)).data,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: connectionsQueryKey() });
    },
  });
}
