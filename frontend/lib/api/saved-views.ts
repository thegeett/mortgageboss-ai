/**
 * Saved views data layer (LP-UI-015).
 *
 * A saved view is a named filter over the pipeline, owned by a user and scoped
 * to a company. Shared views are readable by the whole company and writable only
 * by their owner — `is_mine` comes from the server so that judgement lives in
 * one place rather than being re-derived in every consumer.
 */
import { apiClient } from "@/lib/api/client";
import type { LoanFileStatus } from "@/lib/types/loan-file";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

const API_V1 = "/api/v1";

/** Mirrors the backend `SavedViewSort`. */
export type SavedViewSort = "attention" | "updated_desc" | "updated_asc" | "amount_desc";

/**
 * What a view filters on.
 *
 * Deliberately the same vocabulary the list endpoint accepts. Note what is NOT
 * here: an assignee filter. LP-UI-014 asks for "current user" as a value, and a
 * loan file has no owner in the data model — see docs/tickets/LP-UI-015.md.
 */
export interface SavedViewFilters {
  statuses: LoanFileStatus[];
  search: string | null;
}

export interface SavedView {
  id: string;
  name: string;
  filters: SavedViewFilters;
  sort: SavedViewSort;
  is_shared: boolean;
  owner_user_id: string;
  /** True when the caller owns it — gates edit and delete. */
  is_mine: boolean;
  created_at: string;
  updated_at: string;
}

export interface SavedViewCreate {
  name: string;
  filters?: Partial<SavedViewFilters>;
  sort?: SavedViewSort;
  is_shared?: boolean;
}

/** Every field optional: a partial update must not reset what it omits. */
export interface SavedViewUpdate {
  name?: string;
  filters?: Partial<SavedViewFilters>;
  sort?: SavedViewSort;
  is_shared?: boolean;
}

export const savedViewsQueryKey = ["saved-views"] as const;

export async function fetchSavedViews(): Promise<SavedView[]> {
  const res = await apiClient.get<SavedView[]>(`${API_V1}/saved-views`);
  return res.data;
}

export function useSavedViews() {
  return useQuery({ queryKey: savedViewsQueryKey, queryFn: fetchSavedViews });
}

export function useCreateSavedView() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (view: SavedViewCreate) =>
      (await apiClient.post<SavedView>(`${API_V1}/saved-views`, view)).data,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: savedViewsQueryKey }),
  });
}

export function useUpdateSavedView() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, ...update }: SavedViewUpdate & { id: string }) =>
      (await apiClient.patch<SavedView>(`${API_V1}/saved-views/${id}`, update)).data,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: savedViewsQueryKey }),
  });
}

export function useDeleteSavedView() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) => {
      await apiClient.delete(`${API_V1}/saved-views/${id}`);
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: savedViewsQueryKey }),
  });
}
