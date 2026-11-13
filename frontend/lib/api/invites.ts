/**
 * Staff invitations (LP-MB-Admin-04).
 *
 * Admin calls need `users.manage`. The two public calls (`lookupInvite`, `acceptInvite`) need no
 * session: the token is the credential, and it travels in the request BODY, never a path or query,
 * so it reaches no server log.
 */
import { apiClient } from "@/lib/api/client";
import type { AuthTokenResponse, User } from "@/lib/auth/types";
import { useAuthStore } from "@/lib/stores/auth-store";
import type { Invite, InviteIssued, InviteLookup } from "@/lib/types/invites";
import type { Role } from "@/lib/types/users";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

const INVITES = "/api/v1/invites";
export const INVITES_KEY = ["invites"];

export function useInvites() {
  return useQuery({
    queryKey: INVITES_KEY,
    queryFn: async () => (await apiClient.get<Invite[]>(INVITES)).data,
  });
}

/** After any change the list is re-read, and the audit log is stale. */
function useRefresh() {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({ queryKey: INVITES_KEY });
    void queryClient.invalidateQueries({ queryKey: ["audit-log"] });
  };
}

export function useCreateInvite() {
  const refresh = useRefresh();
  return useMutation({
    mutationFn: async (body: { email: string; roles: Role[] }) =>
      (await apiClient.post<InviteIssued>(INVITES, body)).data,
    onSuccess: refresh,
  });
}

export function useResendInvite() {
  const refresh = useRefresh();
  return useMutation({
    mutationFn: async (id: string) =>
      (await apiClient.post<InviteIssued>(`${INVITES}/${id}/resend`)).data,
    onSuccess: refresh,
  });
}

export function useRevokeInvite() {
  const refresh = useRefresh();
  return useMutation({
    mutationFn: async (id: string) =>
      (await apiClient.post<Invite>(`${INVITES}/${id}/revoke`)).data,
    onSuccess: refresh,
  });
}

export async function lookupInvite(token: string): Promise<InviteLookup> {
  return (await apiClient.post<InviteLookup>(`${INVITES}/lookup`, { token })).data;
}

/** Create the account and sign in, stored the way `login` stores a session. */
export async function acceptInvite(body: {
  token: string;
  first_name: string;
  last_name: string;
  password: string;
}): Promise<User> {
  const { access_token, user } = (
    await apiClient.post<AuthTokenResponse>(`${INVITES}/accept`, body)
  ).data;
  useAuthStore.getState().setAuth({ accessToken: access_token, user });
  return user;
}
