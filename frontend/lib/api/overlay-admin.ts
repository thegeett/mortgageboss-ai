/**
 * Overlay admin data layer (LP-87) — list lenders, view + edit a lender's overlay.
 * Admin-only on the backend (require_role) + tenant-scoped; this layer just talks to it.
 */
import { apiClient } from "@/lib/api/client";
import type { LenderSummary } from "@/lib/types/lender";
import type { LenderOverlayView, OverlayUpdateRequest } from "@/lib/types/overlay-admin";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

const ADMIN_LENDERS = "/api/v1/admin/lenders";

export async function fetchOverlayLenders(): Promise<LenderSummary[]> {
  const res = await apiClient.get<LenderSummary[]>(ADMIN_LENDERS);
  return res.data;
}

export async function fetchLenderOverlay(id: string): Promise<LenderOverlayView> {
  const res = await apiClient.get<LenderOverlayView>(`${ADMIN_LENDERS}/${id}/overlay`);
  return res.data;
}

export async function updateLenderOverlay(
  id: string,
  body: OverlayUpdateRequest,
): Promise<LenderOverlayView> {
  const res = await apiClient.put<LenderOverlayView>(`${ADMIN_LENDERS}/${id}/overlay`, body);
  return res.data;
}

export function useOverlayLenders() {
  return useQuery({ queryKey: ["overlay-lenders"], queryFn: fetchOverlayLenders });
}

export function useLenderOverlay(id: string) {
  return useQuery({
    queryKey: ["lender-overlay", id],
    queryFn: () => fetchLenderOverlay(id),
    enabled: Boolean(id),
  });
}

export function useUpdateLenderOverlay(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: OverlayUpdateRequest) => updateLenderOverlay(id, body),
    onSuccess: (data) => {
      queryClient.setQueryData(["lender-overlay", id], data);
    },
  });
}
