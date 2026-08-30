import { apiClient } from "@/lib/api/client";
import { useQuery } from "@tanstack/react-query";
import { isAxiosError } from "axios";
import { useEffect } from "react";

/**
 * One rendered page of a document (LP-UI-030).
 *
 * The image and the page's POINT geometry arrive together, from one request. A
 * highlight rectangle from the text layer is expressed in points, so a caller
 * needs both to place it — and fetching them separately is how the two drift.
 *
 * The blob is an object URL, which the browser holds until it is revoked. The
 * hook's consumer revokes on unmount (`useRevokeOnUnmount`), because a reviewer
 * paging through a forty-page document otherwise leaks forty decoded images.
 */
export interface PageImage {
  url: string;
  widthPoints: number;
  heightPoints: number;
  zoom: number;
}

export function pageImageQueryKey(documentId: string, page: number) {
  return ["document-page", documentId, page] as const;
}

export async function fetchPageImage(documentId: string, page: number): Promise<PageImage> {
  const response = await apiClient.get(`/api/v1/documents/${documentId}/page/${page}`, {
    responseType: "blob",
  });
  const header = (name: string) => Number(response.headers[name.toLowerCase()] ?? 0);
  return {
    url: URL.createObjectURL(response.data as Blob),
    widthPoints: header("X-Page-Width-Points"),
    heightPoints: header("X-Page-Height-Points"),
    zoom: header("X-Page-Zoom") || 1,
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
  return useQuery({
    queryKey: pageImageQueryKey(documentId ?? "", page),
    queryFn: () => fetchPageImage(documentId as string, page),
    enabled: Boolean(documentId) && page > 0,
    retry: (failureCount, error) =>
      !(isAxiosError(error) && error.response?.status === 404) && failureCount < 1,
    staleTime: 5 * 60 * 1000,
  });
}

/** Revoke an object URL when the component holding it goes away. */
export function useRevokeOnUnmount(url: string | undefined) {
  useEffect(() => {
    if (!url) return;
    return () => URL.revokeObjectURL(url);
  }, [url]);
}
