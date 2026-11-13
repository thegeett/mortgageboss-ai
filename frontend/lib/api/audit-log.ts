/** The company audit log, read-only (LP-MB-Admin-03). `audit.view` on the server. */
import { apiClient } from "@/lib/api/client";
import type { AuditFilters, AuditPage } from "@/lib/types/users";
import { useInfiniteQuery } from "@tanstack/react-query";

const AUDIT_LOG = "/api/v1/audit-log";

export async function fetchAuditPage(
  filters: AuditFilters,
  before: string | null,
  limit: number,
): Promise<AuditPage> {
  const params = { ...filters, limit, ...(before ? { before } : {}) };
  return (await apiClient.get<AuditPage>(AUDIT_LOG, { params })).data;
}

/** Newest first; `fetchNextPage` follows the server's cursor. */
export function useAuditLog(filters: AuditFilters, limit = 50) {
  return useInfiniteQuery({
    queryKey: ["audit-log", filters, limit],
    queryFn: ({ pageParam }) => fetchAuditPage(filters, pageParam, limit),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
  });
}
