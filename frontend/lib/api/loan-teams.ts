/**
 * A loan file's team and who can be put on one (LP-MB-Admin-05).
 *
 * Changing a team is for an Admin, or the loan officer on their own file; the server decides and
 * says so in `can_change`, which the Team card reads instead of guessing from roles.
 */
import { apiClient } from "@/lib/api/client";
import type { FileTeam } from "@/lib/types/loan-file";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

export interface TeamView extends FileTeam {
  can_change: boolean;
}

/** A person who can take a slot, with how many live files they are on now. */
export interface AssignablePerson {
  id: string;
  name: string;
  roles: string[];
  file_count: number;
}

export type Slot = "loan_officer" | "processor";

const teamPath = (fileId: string) => `/api/v1/loan-files/${fileId}/team`;

export function useTeam(fileId: string) {
  return useQuery({
    queryKey: ["loan-team", fileId],
    queryFn: async () => (await apiClient.get<TeamView>(teamPath(fileId))).data,
    enabled: Boolean(fileId),
  });
}

export function useAssignable(slot: Slot, options?: { enabled?: boolean }) {
  return useQuery({
    enabled: options?.enabled,
    queryKey: ["assignable", slot],
    queryFn: async () =>
      (
        await apiClient.get<AssignablePerson[]>("/api/v1/users/assignable", {
          params: { team_role: slot },
        })
      ).data,
  });
}

/** After a team change: the team, the file (its loan-officer text) and the lists are stale. */
function useTeamChange<T>(fileId: string, run: (body: T) => Promise<TeamView>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: run,
    onSuccess: (team) => {
      queryClient.setQueryData(["loan-team", fileId], team);
      void queryClient.invalidateQueries({ queryKey: ["loan-file", fileId] });
      void queryClient.invalidateQueries({ queryKey: ["loan-files"] });
      void queryClient.invalidateQueries({ queryKey: ["assignable"] });
    },
  });
}

export function useSetLoanOfficer(fileId: string) {
  return useTeamChange(
    fileId,
    async (userId: string | null) =>
      (await apiClient.put<TeamView>(`${teamPath(fileId)}/loan-officer`, { user_id: userId })).data,
  );
}

export function useAddProcessor(fileId: string) {
  return useTeamChange(
    fileId,
    async (userId: string) =>
      (await apiClient.post<TeamView>(`${teamPath(fileId)}/members`, { user_id: userId })).data,
  );
}

export function useRemoveMember(fileId: string) {
  return useTeamChange(
    fileId,
    async (memberId: string) =>
      (await apiClient.delete<TeamView>(`${teamPath(fileId)}/members/${memberId}`)).data,
  );
}

/** Move every file a person works to someone else (`users.manage`). */
export async function reassignLoans(fromUserId: string, toUserId: string): Promise<number> {
  const res = await apiClient.post<{ moved: number }>(
    `/api/v1/users/${fromUserId}/reassign-loans`,
    { to_user_id: toUserId },
  );
  return res.data.moved;
}
