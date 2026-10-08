/**
 * LP-925 (S3-11): a lender's condition settings. Entered once per lender, used on every file — the plan,
 * the drafts and the package read the same stored settings. (LP-965 removed its "codes to review": nothing
 * is mapped per lender code any more.)
 */
import { apiClient } from "@/lib/api/client";
import type { LenderDetail } from "@/lib/types/lender";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

const LENDERS_PATH = "/api/v1/lenders";

export interface LenderConditionSettings {
  mortgagee_clause: string | null;
  /** The clause shown came from the newest approval letter and has not been saved yet. */
  clause_from_letter: boolean;
  /** "20:00". */
  upload_cutoff: string | null;
  upload_cutoff_tz: string;
  /** "note", "name_of_source", "date_verified". */
  upload_fields: string[];
  lender_orders_final_inspection: boolean;
  /** LP-945 — the lender verifies a self-employed borrower's business exists (IE-08). */
  lender_verifies_business_existence: boolean;
  lender_orders_title_insurance_payoffs: boolean;
  new_files_lender_processing: boolean;
}

export function useLender(lenderId: string) {
  return useQuery({
    queryKey: ["lender", lenderId],
    queryFn: async () => (await apiClient.get<LenderDetail>(`${LENDERS_PATH}/${lenderId}`)).data,
  });
}

export function useLenderConditionSettings(lenderId: string) {
  return useQuery({
    queryKey: ["lender-condition-settings", lenderId],
    queryFn: async () =>
      (
        await apiClient.get<LenderConditionSettings>(
          `${LENDERS_PATH}/${lenderId}/condition-settings`,
        )
      ).data,
  });
}

export function useSaveLenderConditionSettings(lenderId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: Omit<LenderConditionSettings, "clause_from_letter">) =>
      (
        await apiClient.put<LenderConditionSettings>(
          `${LENDERS_PATH}/${lenderId}/condition-settings`,
          body,
        )
      ).data,
    onSuccess: (data) => {
      queryClient.setQueryData(["lender-condition-settings", lenderId], data);
    },
  });
}
