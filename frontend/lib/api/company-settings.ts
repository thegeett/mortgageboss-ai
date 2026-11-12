/**
 * The caller's company settings (LP-MB-Admin-02). `company.settings.manage` on the server.
 */
import { fetchCurrentUser } from "@/lib/api/auth";
import { apiClient } from "@/lib/api/client";
import { useAuthStore } from "@/lib/stores/auth-store";
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
    onSuccess: async (data) => {
      queryClient.setQueryData(QUERY_KEY, data);
      // A setting can change what this user may do (`loan.create` comes from one), and the
      // permissions in the store were resolved at sign-in. Re-read them so the UI follows now.
      // Other signed-in users pick the change up on their next refresh; the API is current for
      // everyone already. Best effort: the save itself has succeeded either way.
      try {
        const user = await fetchCurrentUser();
        useAuthStore.setState({ user });
      } catch {
        // Left as it was; the next session refresh brings it up to date.
      }
    },
  });
}
