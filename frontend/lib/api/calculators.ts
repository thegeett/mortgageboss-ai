/**
 * The four LP-87 calculators data layer — the read + the override mutations.
 *
 * Parameterized by the calculator name (mortgage_insurance / self_employed / reserves /
 * max_loan). Override endpoints return the recomputed view, so a mutation primes the query
 * cache directly (real-time recalc, one round-trip). The activity feed is invalidated so the
 * audited override appears there too. (Same shape as the LP-76/77 DTI/LTV data layer.)
 */
import { apiClient } from "@/lib/api/client";
import type { CalcOverrideInput, CalculatorName, CalculatorView } from "@/lib/types/calculators";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { isAxiosError } from "axios";

const API_V1 = "/api/v1";

export const calcQueryKey = (identifier: string, calculator: CalculatorName) =>
  ["calculator", identifier, calculator] as const;

function base(identifier: string, calculator: CalculatorName): string {
  return `${API_V1}/loan-files/${identifier}/calculators/${calculator}`;
}

export async function fetchCalculator(
  identifier: string,
  calculator: CalculatorName,
): Promise<CalculatorView> {
  const res = await apiClient.get<CalculatorView>(base(identifier, calculator));
  return res.data;
}

/** A 404 (missing or out-of-company) won't change on retry — surface it. */
function noRetryOn404(failureCount: number, error: unknown): boolean {
  return !(isAxiosError(error) && error.response?.status === 404) && failureCount < 1;
}

export function useCalculator(identifier: string, calculator: CalculatorName) {
  return useQuery({
    queryKey: calcQueryKey(identifier, calculator),
    queryFn: () => fetchCalculator(identifier, calculator),
    enabled: Boolean(identifier),
    retry: noRetryOn404,
  });
}

export async function setCalculatorOverride(
  identifier: string,
  calculator: CalculatorName,
  fieldKey: string,
  input: CalcOverrideInput,
): Promise<CalculatorView> {
  const res = await apiClient.put<CalculatorView>(
    `${base(identifier, calculator)}/overrides/${fieldKey}`,
    input,
  );
  return res.data;
}

export async function clearCalculatorOverride(
  identifier: string,
  calculator: CalculatorName,
  fieldKey: string,
): Promise<CalculatorView> {
  const res = await apiClient.delete<CalculatorView>(
    `${base(identifier, calculator)}/overrides/${fieldKey}`,
  );
  return res.data;
}

export function useSetCalculatorOverride(identifier: string, calculator: CalculatorName) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ fieldKey, input }: { fieldKey: string; input: CalcOverrideInput }) =>
      setCalculatorOverride(identifier, calculator, fieldKey, input),
    onSuccess: (data) => {
      queryClient.setQueryData(calcQueryKey(identifier, calculator), data);
      void queryClient.invalidateQueries({ queryKey: ["loan-file-activity", identifier] });
    },
  });
}

export function useClearCalculatorOverride(identifier: string, calculator: CalculatorName) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (fieldKey: string) => clearCalculatorOverride(identifier, calculator, fieldKey),
    onSuccess: (data) => {
      queryClient.setQueryData(calcQueryKey(identifier, calculator), data);
      void queryClient.invalidateQueries({ queryKey: ["loan-file-activity", identifier] });
    },
  });
}
