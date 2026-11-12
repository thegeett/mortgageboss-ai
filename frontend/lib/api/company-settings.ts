/**
 * The caller's company settings (LP-MB-Admin-02). `company.settings.manage` on the server.
 */
import { apiClient } from "@/lib/api/client";
import type { CompanySettings, CompanySettingsUpdate } from "@/lib/types/company-settings";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

const COMPANY_SETTINGS = "/api/v1/company/settings";
const QUERY_KEY = ["company-settings"];

export async function fetchCompanySettings(): Promise<CompanySettings> {
  const res = await apiClient.get<CompanySettings>(COMPANY_SETTINGS);
  return res.data;
}

export async function updateCompanySettings(body: CompanySettingsUpdate): Promise<CompanySettings> {
  const res = await apiClient.patch<CompanySettings>(COMPANY_SETTINGS, body);
  return res.data;
}

export function useCompanySettings() {
  return useQuery({ queryKey: QUERY_KEY, queryFn: fetchCompanySettings });
}

export function useUpdateCompanySettings() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: updateCompanySettings,
    onSuccess: (data) => {
      queryClient.setQueryData(QUERY_KEY, data);
    },
  });
}
