import { apiClient } from "@/lib/api/client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { isAxiosError } from "axios";
import { useEffect } from "react";

/**
 * One rendered page of a document (LP-UI-030).
 *
 * The image and the page's POINT geometry arrive together, from one request. A
 * highlight rectangle from the text layer is expressed in points, so a caller
 * needs both to place it — and fetching them separately is how the two drift.
 *
 * The blob is an object URL, which the browser holds until it is revoked — so
 * something must revoke it, or a reviewer paging through a forty-page document
 * leaks forty decoded images.
 *
 * IT IS REVOKED WHEN THE CACHE DROPS THE ENTRY, not when a component unmounts.
 * The first version revoked in an effect cleanup keyed on the url, which also
 * runs when the url merely CHANGES — so paging 1 → 2 revoked page 1's url while
 * TanStack went on serving that exact object from cache for five minutes. Paging
 * back showed a dead blob: `naturalWidth: 0`, which the browser draws as its
 * broken-image icon. Reported from the app, then reproduced.
 *
 * The url's lifetime belongs to the cached object, so the revoke belongs to the
 * cache's own eviction.
 */
export interface PageImage {
  url: string;
  widthPoints: number;
  heightPoints: number;
  zoom: number;
  /**
   * How many pages the document has, so the reviewer can say "Page 1 of 5" and
   * stop at the last one. `null` when the server did not say — the control then
   * only guards the lower bound rather than inventing a ceiling.
   */
  pageCount: number | null;
}

/** The cache namespace, named once so the eviction hook cannot drift from it. */
const PAGE_IMAGE_KEY = "document-page";

export function pageImageQueryKey(documentId: string, page: number) {
  return [PAGE_IMAGE_KEY, documentId, page] as const;
}

export async function fetchPageImage(documentId: string, page: number): Promise<PageImage> {
  const response = await apiClient.get(`/api/v1/documents/${documentId}/page/${page}`, {
    responseType: "blob",
  });
  // These arrive only because the API names them in `expose_headers` — a browser
  // reads no custom response header across origins otherwise, and they had been
  // silently absent (width and height reading back as 0) since LP-UI-030.
  const header = (name: string) => Number(response.headers[name.toLowerCase()] ?? 0);
  const count = header("X-Page-Count");
  return {
    url: URL.createObjectURL(response.data as Blob),
    widthPoints: header("X-Page-Width-Points"),
    heightPoints: header("X-Page-Height-Points"),
    zoom: header("X-Page-Zoom") || 1,
    // 0 means "not told", which is not the same as a document of zero pages.
    pageCount: count > 0 ? count : null,
  };
}

/**
 * A document's page, or an error the caller renders as "no page image".
 *
 * A 404 here is ordinary, not exceptional: it is a scan, a non-PDF, or a page
 * the document does not have. Measured on stored documents — 12 of 105 PDFs have
 * no text layer, and a model-cited page is out of range on ~4% of fields — so
 * retrying it would just be slower on the common case.
 */
export function usePageImage(documentId: string | null, page: number) {
  useRevokeOnEviction();
  return useQuery({
    queryKey: pageImageQueryKey(documentId ?? "", page),
    queryFn: () => fetchPageImage(documentId as string, page),
    enabled: Boolean(documentId) && page > 0,
    retry: (failureCount, error) =>
      !(isAxiosError(error) && error.response?.status === 404) && failureCount < 1,
    staleTime: 5 * 60 * 1000,
  });
}

/**
 * Revoke a page image's object URL when the query cache evicts it.
 *
 * Subscribing per hook instance is deliberate and safe: `revokeObjectURL` on an
 * already-revoked url is a no-op, and the subscription is torn down with the
 * component. What matters is that SOMETHING outlives the component that first
 * fetched the page, because the cached url does.
 */
function useRevokeOnEviction(): void {
  const queryClient = useQueryClient();
  useEffect(
    () =>
      queryClient.getQueryCache().subscribe((event) => {
        if (event.type !== "removed") return;
        const key = event.query.queryKey;
        if (!Array.isArray(key) || key[0] !== PAGE_IMAGE_KEY) return;
        const data = event.query.state.data as PageImage | undefined;
        if (data?.url) URL.revokeObjectURL(data.url);
      }),
    [queryClient],
  );
}
