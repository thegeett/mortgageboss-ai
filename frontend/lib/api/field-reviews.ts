import { apiClient } from "@/lib/api/client";
import { documentDetailQueryKey } from "@/lib/api/documents";
import type { FieldVerdict } from "@/lib/types/document";
import { useMutation, useQueryClient } from "@tanstack/react-query";

/**
 * A processor's verdict on one extracted field (LP-UI-033).
 *
 * The verdict lives beside the extracted value, never on top of it: a correction
 * records what the processor says is right without rewriting what the model read,
 * so "what did the model actually say?" stays answerable.
 */
export type { FieldVerdict } from "@/lib/types/document";

export interface FieldReviewInput {
  fieldKey: string;
  verdict: FieldVerdict;
  /** Required for `corrected`. */
  correctedValue?: string;
  /** Required for `rejected` — a field nobody could verify, with no reason why,
   * tells the next processor nothing. */
  note?: string;
}

export function useRecordFieldReview(documentId: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: FieldReviewInput) => {
      await apiClient.put(`/api/v1/documents/${documentId}/reviews`, {
        field_key: input.fieldKey,
        verdict: input.verdict,
        corrected_value: input.correctedValue ?? null,
        note: input.note ?? null,
      });
    },
    onSuccess: () => {
      // The detail response carries the verdict beside the scrutiny, so one
      // invalidation refreshes both rather than leaving them a tick apart.
      if (documentId) {
        void queryClient.invalidateQueries({ queryKey: documentDetailQueryKey(documentId) });
      }
    },
  });
}

export function useRevertFieldReview(documentId: string | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (fieldKey: string) => {
      await apiClient.delete(`/api/v1/documents/${documentId}/reviews/${fieldKey}`);
    },
    onSuccess: () => {
      if (documentId) {
        void queryClient.invalidateQueries({ queryKey: documentDetailQueryKey(documentId) });
      }
    },
  });
}
