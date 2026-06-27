/**
 * Documents data layer (LP-43): typed fetches + TanStack Query hooks.
 *
 * The signature behaviour is **live status polling**: `useLoanFileDocuments`
 * uses a *function* `refetchInterval` that returns ~2.5s while any document is
 * still being processed (non-terminal) and `false` once every document is
 * settled (COMPLETED / NEEDS_REVIEW / FAILED). So the list updates in
 * near-real-time during processing and stops polling once nothing can change —
 * the `Document.status` (driven by the LP-42 pipeline) is the source of truth.
 */
import { apiClient } from "@/lib/api/client";
import { hasInProgressDocuments } from "@/lib/loan-files/documents";
import type {
  DocumentDetailResponse,
  DocumentResponse,
  TextLayerExtraction,
} from "@/lib/types/document";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { isAxiosError } from "axios";

const API_V1 = "/api/v1";
export const POLL_INTERVAL_MS = 2500;
// Backstop: stop auto-polling after this many fetches even if a document is
// still in a non-terminal state, so a document that won't advance — no Celery
// worker running, or a pipeline that died — doesn't make the page hammer the
// endpoint forever. Normal processing settles in a few polls (well under this
// cap); a refresh resumes polling. ~40 × 2.5s ≈ 100s.
export const MAX_STATUS_POLLS = 40;

/**
 * The polling interval for the documents list: keep polling while any document
 * is in-progress, but stop once everything is terminal OR the backstop is hit.
 * Extracted (and exported) so the backstop is unit-testable.
 */
export function documentsRefetchInterval(
  documents: DocumentResponse[] | undefined,
  fetchCount: number,
): number | false {
  if (!documents || !hasInProgressDocuments(documents)) return false;
  if (fetchCount > MAX_STATUS_POLLS) return false; // stuck doc → stop hammering
  return POLL_INTERVAL_MS;
}

/** A 404 (missing or out-of-company) won't change on retry — surface it. */
function noRetryOn404(failureCount: number, error: unknown): boolean {
  return !(isAxiosError(error) && error.response?.status === 404) && failureCount < 1;
}

export const documentsQueryKey = (fileId: string) => ["loan-file-documents", fileId] as const;
export const documentDetailQueryKey = (documentId: string) =>
  ["document-detail", documentId] as const;

// --- List with live polling ------------------------------------------------- //

export async function fetchLoanFileDocuments(fileId: string): Promise<DocumentResponse[]> {
  const res = await apiClient.get<DocumentResponse[]>(`${API_V1}/loan-files/${fileId}/documents`);
  return res.data;
}

export function useLoanFileDocuments(fileId: string) {
  return useQuery({
    queryKey: documentsQueryKey(fileId),
    queryFn: () => fetchLoanFileDocuments(fileId),
    enabled: Boolean(fileId),
    retry: noRetryOn404,
    // Poll WHILE any document is in-progress; STOP once all are terminal or the
    // backstop trips (dataUpdateCount = the number of successful fetches so far).
    refetchInterval: (query) =>
      documentsRefetchInterval(query.state.data, query.state.dataUpdateCount),
  });
}

// --- Single-document detail (drawer) ---------------------------------------- //

export async function fetchDocumentDetail(documentId: string): Promise<DocumentDetailResponse> {
  const res = await apiClient.get<DocumentDetailResponse>(`${API_V1}/documents/${documentId}`);
  return res.data;
}

export function useDocumentDetail(documentId: string | null) {
  return useQuery({
    queryKey: documentDetailQueryKey(documentId ?? ""),
    queryFn: () => fetchDocumentDetail(documentId as string),
    enabled: Boolean(documentId), // only when the drawer is open
    retry: noRetryOn404,
  });
}

// --- Upload (multipart, multiple) ------------------------------------------- //

export async function uploadDocuments(fileId: string, files: File[]): Promise<DocumentResponse[]> {
  const form = new FormData();
  for (const file of files) {
    form.append("files", file);
  }
  const res = await apiClient.post<DocumentResponse[]>(
    `${API_V1}/loan-files/${fileId}/documents`,
    form,
    { headers: { "Content-Type": "multipart/form-data" } },
  );
  return res.data;
}

export function useUploadDocuments(fileId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (files: File[]) => uploadDocuments(fileId, files),
    onSuccess: () => {
      // New PENDING docs appear and polling resumes.
      void queryClient.invalidateQueries({ queryKey: documentsQueryKey(fileId) });
    },
  });
}

// --- Soft delete ------------------------------------------------------------ //

export async function deleteDocument(documentId: string): Promise<void> {
  await apiClient.delete(`${API_V1}/documents/${documentId}`);
}

export function useDeleteDocument(fileId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (documentId: string) => deleteDocument(documentId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: documentsQueryKey(fileId) });
    },
  });
}

// --- Manual type override (LP-44) ------------------------------------------- //

export async function overrideDocumentType(
  documentId: string,
  documentType: string,
): Promise<DocumentResponse> {
  const res = await apiClient.patch<DocumentResponse>(`${API_V1}/documents/${documentId}`, {
    document_type: documentType,
  });
  return res.data;
}

/**
 * Override a document's type, then re-extract (LP-44). On success, invalidate the
 * list + this document's detail so live polling shows the re-processing (the
 * server enqueues the existing LP-39c re-extraction).
 */
export function useOverrideDocumentType(fileId: string, documentId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (documentType: string) => overrideDocumentType(documentId, documentType),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: documentsQueryKey(fileId) });
      void queryClient.invalidateQueries({ queryKey: documentDetailQueryKey(documentId) });
    },
  });
}

// --- Versioning + staleness (LP-71) ----------------------------------------- //

const activityQueryKey = (fileId: string) => ["loan-file-activity", fileId] as const;
export const documentVersionsQueryKey = (documentId: string) =>
  ["document-versions", documentId] as const;

/** Explicitly replace a document with a new upload (old → historical, new → current). */
export async function replaceDocument(documentId: string, file: File): Promise<DocumentResponse> {
  const form = new FormData();
  form.append("file", file);
  const res = await apiClient.post<DocumentResponse>(
    `${API_V1}/documents/${documentId}/replace`,
    form,
    { headers: { "Content-Type": "multipart/form-data" } },
  );
  return res.data;
}

export function useReplaceDocument(fileId: string, documentId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => replaceDocument(documentId, file),
    onSuccess: () => {
      // The new version appears (processing); the old goes historical.
      void queryClient.invalidateQueries({ queryKey: documentsQueryKey(fileId) });
      void queryClient.invalidateQueries({ queryKey: documentDetailQueryKey(documentId) });
      void queryClient.invalidateQueries({ queryKey: documentVersionsQueryKey(documentId) });
      void queryClient.invalidateQueries({ queryKey: activityQueryKey(fileId) });
    },
  });
}

/** Resolve a flagged-stale document — waive or accept (replace is its own flow). */
export async function resolveStaleness(
  documentId: string,
  action: "waive" | "accept",
  reason?: string,
): Promise<DocumentResponse> {
  const res = await apiClient.post<DocumentResponse>(
    `${API_V1}/documents/${documentId}/resolve-staleness`,
    { action, reason: reason ?? null },
  );
  return res.data;
}

export function useResolveStaleness(fileId: string, documentId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ action, reason }: { action: "waive" | "accept"; reason?: string }) =>
      resolveStaleness(documentId, action, reason),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: documentsQueryKey(fileId) });
      void queryClient.invalidateQueries({ queryKey: documentDetailQueryKey(documentId) });
      void queryClient.invalidateQueries({ queryKey: activityQueryKey(fileId) });
    },
  });
}

/** The document's version group (oldest → newest). Only fetched when the drawer needs it. */
export async function fetchDocumentVersions(documentId: string): Promise<DocumentResponse[]> {
  const res = await apiClient.get<DocumentResponse[]>(`${API_V1}/documents/${documentId}/versions`);
  return res.data;
}

export function useDocumentVersions(documentId: string | null, enabled: boolean) {
  return useQuery({
    queryKey: documentVersionsQueryKey(documentId ?? ""),
    queryFn: () => fetchDocumentVersions(documentId as string),
    enabled: Boolean(documentId) && enabled,
    retry: noRetryOn404,
  });
}

// --- Dev-only text-layer extraction (LP-40; non-production) ------------------ //

export async function fetchDevTextLayer(documentId: string): Promise<TextLayerExtraction> {
  const res = await apiClient.post<TextLayerExtraction>(
    `${API_V1}/dev/documents/${documentId}/extract-text-layer`,
  );
  return res.data;
}

export function useDevTextLayer(documentId: string) {
  return useMutation({
    mutationFn: () => fetchDevTextLayer(documentId),
  });
}

// --- Authed download -------------------------------------------------------- //

/**
 * Download a document's original bytes through the authed endpoint (the axios
 * client attaches the Bearer token), then trigger a browser save with the
 * original filename. Returns nothing; throws on failure for the caller to toast.
 */
export async function downloadDocument(documentId: string, filename: string): Promise<void> {
  const res = await apiClient.get(`${API_V1}/documents/${documentId}/download`, {
    responseType: "blob",
  });
  const url = URL.createObjectURL(res.data as Blob);
  try {
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
  } finally {
    URL.revokeObjectURL(url);
  }
}
