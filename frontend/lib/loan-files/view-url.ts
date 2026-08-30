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
import type { LoanFileStatus } from "@/lib/types/loan-file";

export interface PipelineUrlState {
  statuses: LoanFileStatus[];
  search: string;
  viewId: string | null;
}

export const EMPTY_STATE: PipelineUrlState = { statuses: [], search: "", viewId: null };

/** Read filter state out of a `URLSearchParams`. Unknown keys are ignored. */
export function readPipelineUrl(params: URLSearchParams): PipelineUrlState {
  return {
    // Repeated `status` params, matching the list endpoint's own shape.
    statuses: params.getAll("status") as LoanFileStatus[],
    search: params.get("q") ?? "",
    viewId: params.get("view"),
  };
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
