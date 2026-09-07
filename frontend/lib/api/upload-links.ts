/**
 * Secure upload links (LP-815) — minted by a processor, redeemed by a borrower.
 *
 * ONLY THE PROCESSOR SIDE IS HERE. The borrower's page is outside `(protected)` and uses plain
 * `fetch`: `apiClient` attaches an `Authorization` header and, on a 401, attempts a silent refresh
 * and redirects to the login screen, which is the last thing to do to somebody with no account.
 */
import { apiClient } from "@/lib/api/client";
import type { MintedUploadLink, UploadLinkSummary } from "@/lib/types/upload-link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

const API_V1 = "/api/v1";

export const uploadLinksQueryKey = (fileId: string) => ["upload-links", fileId] as const;

const linksPath = (fileId: string) => `${API_V1}/loan-files/${fileId}/upload-links`;

export function useUploadLinks(fileId: string) {
  return useQuery({
    queryKey: uploadLinksQueryKey(fileId),
    queryFn: async () => (await apiClient.get<UploadLinkSummary[]>(linksPath(fileId))).data,
    enabled: Boolean(fileId),
  });
}

export interface MintInput {
  recipient_email?: string | null;
  ttl_hours?: number;
  purpose?: string | null;
}

export function useMintUploadLink(fileId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: MintInput) =>
      (await apiClient.post<MintedUploadLink>(linksPath(fileId), input)).data,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: uploadLinksQueryKey(fileId) });
    },
  });
}

export function useRevokeUploadLink(fileId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (linkId: string) =>
      (await apiClient.delete<UploadLinkSummary>(`${linksPath(fileId)}/${linkId}`)).data,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: uploadLinksQueryKey(fileId) });
    },
  });
}
