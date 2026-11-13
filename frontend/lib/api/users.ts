/**
 * People (LP-MB-Admin-03). `users.manage` on the server.
 *
 * One query holds the whole list (no pagination: a company's people fit a page); every change
 * writes the returned row back into it, so the table and the open sheet never disagree. Each change
 * also writes an audit row, so the audit queries are marked stale.
 */
import { apiClient } from "@/lib/api/client";
import type { Person, PersonDetailsUpdate, Role } from "@/lib/types/users";
import { type QueryClient, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

const USERS = "/api/v1/users";
export const USERS_KEY = ["users"];

export async function fetchPeople(): Promise<Person[]> {
  return (await apiClient.get<Person[]>(USERS)).data;
}

function replaceRow(queryClient: QueryClient, person: Person) {
  queryClient.setQueryData<Person[]>(USERS_KEY, (rows) =>
    rows?.map((row) => (row.id === person.id ? person : row)),
  );
  void queryClient.invalidateQueries({ queryKey: ["audit-log"] });
}

export function usePeople() {
  return useQuery({ queryKey: USERS_KEY, queryFn: fetchPeople });
}

export function useUpdatePerson(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: PersonDetailsUpdate) =>
      (await apiClient.patch<Person>(`${USERS}/${id}`, body)).data,
    onSuccess: (person) => replaceRow(queryClient, person),
  });
}

export function useSetRoles(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (roles: Role[]) =>
      (await apiClient.put<Person>(`${USERS}/${id}/roles`, { roles })).data,
    onSuccess: (person) => replaceRow(queryClient, person),
  });
}

export function useSetActive(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (active: boolean) =>
      (await apiClient.post<Person>(`${USERS}/${id}/${active ? "reactivate" : "deactivate"}`)).data,
    onSuccess: (person) => replaceRow(queryClient, person),
  });
}
