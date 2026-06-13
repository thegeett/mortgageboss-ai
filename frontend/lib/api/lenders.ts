/** Lenders data layer (LP-32): a typed fetch + TanStack Query hook. */
import { apiClient } from "@/lib/api/client";
import type { LenderSummary } from "@/lib/types/lender";
import { useQuery } from "@tanstack/react-query";

export const LENDERS_PATH = "/api/v1/lenders";

export async function fetchLenders(): Promise<LenderSummary[]> {
  const response = await apiClient.get<LenderSummary[]>(LENDERS_PATH);
  return response.data;
}

export function useLenders() {
  return useQuery({ queryKey: ["lenders"], queryFn: fetchLenders });
}
