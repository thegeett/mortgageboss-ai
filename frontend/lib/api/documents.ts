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
const POLL_INTERVAL_MS = 2500;

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
    // Poll WHILE any document is in-progress; STOP once all are terminal.
    refetchInterval: (query) => {
      const docs = query.state.data;
      return docs && hasInProgressDocuments(docs) ? POLL_INTERVAL_MS : false;
    },
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
