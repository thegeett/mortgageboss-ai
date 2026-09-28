/**
 * The pipeline's filter state, in the URL (LP-UI-014).
 *
 * A processor should be able to paste what they are looking at into Slack and
 * have a colleague see the same thing. That means the URL is the source of
 * truth for filter state, not component state — anything held only in React is
 * invisible to a paste.
 *
 * Kept deliberately small and flat: `?status=in_processing&status=draft` reads
 * as what it is, and matches the query the list endpoint already accepts. A
 * saved view's id rides along as `?view=<id>` so the selection survives too.
 *
 * THE SEARCH IS NOT HERE (LP-933, ADR-405 as amended). It matches borrower
 * names, and "a filter that matches NPI stays out of the shareable URL". It
 * lives in `pipeline-search-store.ts`. `q` is neither read nor written: a link
 * that still carries one is stripped by the dashboard, not obeyed.
 */
"use client";

import { LOAN_FILE_STATUS } from "@/lib/status";
import type { LoanFileStatus } from "@/lib/types/loan-file";
import { useSearchParams } from "next/navigation";
import { useMemo } from "react";

export interface PipelineUrlState {
  statuses: LoanFileStatus[];
  viewId: string | null;
}

export const EMPTY_STATE: PipelineUrlState = { statuses: [], viewId: null };

/**
 * Every status this build knows, from the map that is already exhaustive over
 * the union (LP-UI-005). Not a second list — a second list is how the two drift.
 */
function isKnownStatus(value: string): value is LoanFileStatus {
  return Object.hasOwn(LOAN_FILE_STATUS, value);
}

/** Read filter state out of a `URLSearchParams`. Unknown keys are ignored. */
export function readPipelineUrl(params: URLSearchParams): PipelineUrlState {
  return {
    // Repeated `status` params, matching the list endpoint's own shape.
    //
    // FILTERED, not cast. The endpoint types this as `list[LoanFileStatus]`, so
    // FastAPI answers an unknown one with a 422 and the dashboard renders its
    // error state — a URL is a paste-able, bookmarkable artifact, and a typo in
    // one should drop the filter rather than break the page. It also matters the
    // day a status is retired: every saved view and bookmark carrying it would
    // otherwise start failing rather than quietly widening.
    statuses: params.getAll("status").filter(isKnownStatus),
    viewId: params.get("view"),
  };
}

/**
 * True when a URL still carries a search term: a bookmark or pasted link from
 * before LP-933. The dashboard strips it rather than applying it, so the term
 * leaves the address bar and a link opened in a new tab shows no search.
 */
export function carriesSearchTerm(params: URLSearchParams): boolean {
  return params.has("q");
}

/**
 * The parsed URL state, memoised — the ONE place that reads it.
 *
 * Both the dashboard and the context column need this, and both were parsing
 * the URL themselves. Two parsers of one source is the shape that has produced
 * a defect three times in this epic; the cost of the second one here is only
 * that it can drift, which is enough.
 */
export function usePipelineUrl(): PipelineUrlState {
  const searchParams = useSearchParams();
  const query = searchParams.toString();
  return useMemo(() => readPipelineUrl(new URLSearchParams(query)), [query]);
}

/**
 * Serialise filter state to a query string.
 *
 * Empty values are omitted rather than written as blanks, so one filter has
 * one spelling and survives a copy-paste unchanged. There is no search
 * parameter to write: the type has no field for one.
 */
export function writePipelineUrl(state: PipelineUrlState): string {
  const params = new URLSearchParams();
  for (const status of state.statuses) params.append("status", status);
  if (state.viewId) params.set("view", state.viewId);
  const query = params.toString();
  return query ? `?${query}` : "";
}

/**
 * True when anything is filtered — used to choose between "no files" and "no
 * matches". The search is passed in because it is a filter that is not in the
 * URL; leaving it out made "All files" look current while a search was active.
 */
export function isFiltered(state: PipelineUrlState, search = ""): boolean {
  return state.statuses.length > 0 || search.trim() !== "";
}
