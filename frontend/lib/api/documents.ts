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
// ...and after it, SLOW DOWN rather than stop (LP-637 feature 3 review). The backstop was
// calibrated for one upload settling in a few polls; a bulk reprocess legitimately runs for tens
// of minutes, because the worker is serial and each document may take up to its 600s soft limit.
// Stopping dead at ~100s froze the list mid-batch at "Pending" — the exact "watching for documents
// to change, indistinguishable from a slow queue" failure the toast copy exists to prevent. Worse,
// `dataUpdateCount` is cumulative for the query's lifetime and invalidation does not reset it, so a
// processor who had already watched an upload for two minutes got no live polling at all.
export const SLOW_POLL_INTERVAL_MS = 15000;

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
  // The primary stop is the line above — nothing in progress, no polling. Past the budget this
  // backs off rather than giving up, so long-running work stays visible without hammering.
  return fetchCount > MAX_STATUS_POLLS ? SLOW_POLL_INTERVAL_MS : POLL_INTERVAL_MS;
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

// --- The document-type catalog (LP-638) -------------------------------------- //

export interface DocumentTypeOption {
  value: string;
  label: string;
  category: string;
  /** Does choosing this type re-run extraction? Served by the backend — see the hook's note. */
  extracts: boolean;
}

const documentTypesQueryKey = ["document-types"] as const;

export async function fetchDocumentTypes(): Promise<DocumentTypeOption[]> {
  const res = await apiClient.get<DocumentTypeOption[]>(`${API_V1}/documents/types/catalog`);
  return res.data;
}

/**
 * Every type a document can be corrected to (LP-638).
 *
 * FETCHED, NOT HARDCODED. The list this replaces was eight options written when the catalog had
 * three document types; it now has 164, so `closing_disclosure` and 150-odd others could not be
 * chosen at all — and two of the eight were not catalog types, so picking them set a document to a
 * string with no tier, no category and no extractor.
 *
 * Reference data that changes only on deploy, so it is cached for the session rather than refetched
 * every time a drawer opens.
 */
export function useDocumentTypes() {
  return useQuery({
    queryKey: documentTypesQueryKey,
    queryFn: fetchDocumentTypes,
    staleTime: Number.POSITIVE_INFINITY,
  });
}

// --- Reprocess: read the document again from scratch (LP-637) ---------------- //

/** What a bulk reprocess did. `skipped` maps a reason to how many were passed over. */
export interface BulkReprocessResult {
  queued: number;
  queued_document_ids: string[];
  skipped: Record<string, number>;
}

export async function reprocessDocument(
  documentId: string,
  force = false,
): Promise<DocumentResponse> {
  const res = await apiClient.post<DocumentResponse>(
    `${API_V1}/documents/${documentId}/reprocess`,
    { force },
  );
  return res.data;
}

/**
 * Re-run the FULL pipeline on one document — classification included (LP-637).
 *
 * Not the type override: that supplies a type and skips classification, which cannot help a
 * document nobody can name. This is for the ones the classifier got wrong or could not read, and
 * for every document processed before a classifier fix landed.
 *
 * Invalidates the list and this document's detail so the status moves visibly; the server sets it
 * back to PENDING, so live polling shows the pipeline running rather than nothing changing.
 */
export function useReprocessDocument(fileId: string, documentId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (force?: boolean) => reprocessDocument(documentId, force ?? false),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: documentsQueryKey(fileId) });
      void queryClient.invalidateQueries({ queryKey: documentDetailQueryKey(documentId) });
      // The endpoint writes a DOCUMENT_REPROCESSED entry and calls `mark_verification_stale`, so
      // both of those views are wrong without this — the sibling mutations below invalidate
      // activity for exactly the same reason (LP-637 review). Leaving verification meant the tab
      // kept presenting a run the server had just marked out of date.
      void queryClient.invalidateQueries({ queryKey: ["loan-file-activity", fileId] });
      void queryClient.invalidateQueries({ queryKey: ["verification", fileId] });
    },
  });
}

export async function reprocessDocuments(
  fileId: string,
  options: { allDocuments?: boolean; force?: boolean } = {},
): Promise<BulkReprocessResult> {
  const res = await apiClient.post<BulkReprocessResult>(
    `${API_V1}/loan-files/${fileId}/documents/reprocess`,
    { all_documents: options.allDocuments ?? false, force: options.force ?? false },
  );
  return res.data;
}

/**
 * Reprocess a file's documents in one call (LP-637).
 *
 * The default set is bounded server-side to the documents a re-read could plausibly improve, so
 * this is not "spend the whole file's model budget". The result reports what was SKIPPED and why —
 * surface it, because a bulk action that quietly does less than asked leaves a processor waiting
 * for documents that were never sent.
 */
export function useReprocessDocuments(fileId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (options?: { allDocuments?: boolean; force?: boolean }) =>
      reprocessDocuments(fileId, options ?? {}),
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: documentsQueryKey(fileId) });
      // One batch entry is still an entry, and the file is marked stale once (LP-637 review).
      void queryClient.invalidateQueries({ queryKey: ["loan-file-activity", fileId] });
      void queryClient.invalidateQueries({ queryKey: ["verification", fileId] });
      // The drawer may be open on a document in the batch. `queued_document_ids` is exactly the
      // set whose detail is about to change, and was otherwise unused.
      for (const id of result.queued_document_ids) {
        void queryClient.invalidateQueries({ queryKey: documentDetailQueryKey(id) });
      }
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
