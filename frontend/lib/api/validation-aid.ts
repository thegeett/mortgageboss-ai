/**
 * Validation aid data layer (LP-89) — the inventory read + the verdict capture.
 * Admin-only on the backend; this layer just talks to it. Recording a verdict refreshes
 * the inventory (the item's validation_status flips).
 */
import { apiClient } from "@/lib/api/client";
import type { ValidationInventory, VerdictInput } from "@/lib/types/validation-aid";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

const BASE = "/api/v1/admin/validation";

export async function fetchInventory(): Promise<ValidationInventory> {
  const res = await apiClient.get<ValidationInventory>(`${BASE}/inventory`);
  return res.data;
}

export async function recordVerdict(input: VerdictInput): Promise<void> {
  await apiClient.post(`${BASE}/verdicts`, input);
}

export function useValidationInventory() {
  return useQuery({ queryKey: ["validation-inventory"], queryFn: fetchInventory });
}

export function useRecordVerdict() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: VerdictInput) => recordVerdict(input),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["validation-inventory"] });
    },
  });
}
