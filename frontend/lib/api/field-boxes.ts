import { apiClient } from "@/lib/api/client";
import { useQuery } from "@tanstack/react-query";
import { isAxiosError } from "axios";

/**
 * Where each extracted field's value sits on the document (LP-UI-031).
 *
 * Coordinates are normalised 0..1 against the page box, so the overlay works at
 * any zoom without knowing which zoom the image was rendered at.
 *
 * A field is simply ABSENT when its text could not be located — measured at
 * roughly a quarter of real fields (no text layer, snippet not in the document,
 * or a citation naming a page that does not exist). The reviewer's no-box state
 * is ordinary, so absence here is a result rather than a failure.
 */
export interface FieldBox {
  field_key: string;
  page: number;
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

export interface FieldBoxes {
  boxes: FieldBox[];
  /** Fields citing a page the document does not have — surfaced, never corrected silently. */
  fabricated_pages: string[];
  /** Fields whose text was found on a page other than the one cited. */
  relocated: string[];
}

export function fieldBoxesQueryKey(documentId: string) {
  return ["document-boxes", documentId] as const;
}

export function useFieldBoxes(documentId: string | null) {
  return useQuery({
    queryKey: fieldBoxesQueryKey(documentId ?? ""),
    queryFn: async (): Promise<FieldBoxes> => {
      const res = await apiClient.get<FieldBoxes>(`/api/v1/documents/${documentId}/boxes`);
      return res.data;
    },
    enabled: Boolean(documentId),
    // Deriving boxes opens and searches the PDF; the answer only changes when the
    // extraction does, so it is worth holding.
    staleTime: 5 * 60 * 1000,
    retry: (failureCount, error) =>
      !(isAxiosError(error) && error.response?.status === 404) && failureCount < 1,
  });
}
