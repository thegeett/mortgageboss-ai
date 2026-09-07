/**
 * The pipeline's filter state, in the URL (LP-UI-014).
 *
 * A processor should be able to paste what they are looking at into Slack and
 * have a colleague see the same thing. That means the URL is the source of
 * truth for filter state, not component state — anything held only in React is
 * invisible to a paste.
 *
 * Kept deliberately small and flat: `?status=in_processing&status=draft&q=smith`
 * reads as what it is, and matches the query the list endpoint already accepts.
 * A saved view's id rides along as `?view=<id>` so the selection survives too.
 */
"use client";

import { LOAN_FILE_STATUS } from "@/lib/status";
import type { LoanFileStatus } from "@/lib/types/loan-file";
import { useSearchParams } from "next/navigation";
import { useMemo } from "react";

export interface PipelineUrlState {
  statuses: LoanFileStatus[];
  search: string;
  viewId: string | null;
}

export const EMPTY_STATE: PipelineUrlState = { statuses: [], search: "", viewId: null };

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
    search: params.get("q") ?? "",
    viewId: params.get("view"),
  };
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
 * Empty values are omitted rather than written as blanks: `?q=` and no `q` mean
 * the same thing, and only one of them survives a copy-paste unchanged.
 */
export function writePipelineUrl(state: PipelineUrlState): string {
  const params = new URLSearchParams();
  for (const status of state.statuses) params.append("status", status);
  const search = state.search.trim();
  if (search) params.set("q", search);
  if (state.viewId) params.set("view", state.viewId);
  const query = params.toString();
  return query ? `?${query}` : "";
}

/** True when nothing is filtered — used to choose between "no files" and "no matches". */
export function isFiltered(state: PipelineUrlState): boolean {
  return state.statuses.length > 0 || state.search.trim() !== "";
}
