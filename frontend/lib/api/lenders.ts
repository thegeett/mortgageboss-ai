/**
 * Lenders data layer — the picker (LP-32), contacts and the underwriter assignment (LP-813).
 *
 * THE ASSIGNMENT IS NOT PART OF THE FILE PATCH. It has its own endpoint because it has its own
 * refusals: the contact must belong to this company AND be at the file's own lender, and folding
 * it into the general update would put those checks behind a call that writes whatever it is given.
 */
import { apiClient } from "@/lib/api/client";
import type { LenderContact, LenderSummary } from "@/lib/types/lender";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

export const LENDERS_PATH = "/api/v1/lenders";

export async function fetchLenders(): Promise<LenderSummary[]> {
  const response = await apiClient.get<LenderSummary[]>(LENDERS_PATH);
  return response.data;
}

export function useLenders() {
  return useQuery({ queryKey: ["lenders"], queryFn: fetchLenders });
}

export const lenderContactsQueryKey = (lenderId: string | null) =>
  ["lender-contacts", lenderId] as const;

export async function fetchLenderContacts(lenderId: string): Promise<LenderContact[]> {
  return (await apiClient.get<LenderContact[]>(`${LENDERS_PATH}/${lenderId}/contacts`)).data;
}

/** A lender's contacts. Disabled when no lender is chosen — there is nothing to ask for. */
export function useLenderContacts(lenderId: string | null) {
  return useQuery({
    queryKey: lenderContactsQueryKey(lenderId),
    queryFn: () => fetchLenderContacts(lenderId as string),
    enabled: Boolean(lenderId),
  });
}

/**
 * Assign or clear this file's underwriter.
 *
 * INVALIDATES THE FILE, because the server may have changed more than this call asked for: an
 * earlier lender change clears the assignment, and the file is the thing that knows.
 */
export function useSetUnderwriter(fileId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (contactId: string | null) =>
      (
        await apiClient.put<LenderContact | null>(`/api/v1/loan-files/${fileId}/underwriter`, {
          contact_id: contactId,
        })
      ).data,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["loan-file", fileId] });
    },
  });
}

export interface ContactInput {
  name: string;
  email?: string | null;
  phone?: string | null;
  role?: string;
  notes?: string | null;
}

export function useCreateLenderContact(lenderId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: ContactInput) =>
      (await apiClient.post<LenderContact>(`${LENDERS_PATH}/${lenderId}/contacts`, input)).data,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: lenderContactsQueryKey(lenderId) });
    },
  });
}

export function useDeleteLenderContact(lenderId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (contactId: string) => {
      await apiClient.delete(`${LENDERS_PATH}/contacts/${contactId}`);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: lenderContactsQueryKey(lenderId) });
    },
  });
}
