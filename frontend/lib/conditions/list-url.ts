/**
 * The conditions list's filter state, in the URL (LP-913, screens S2-01 / S2-02 / S2-09).
 *
 * MODELLED ON `lib/loan-files/view-url.ts`, WHICH THE SPEC NAMES: "Filters live in the URL (like the
 * pipeline's saved views), so a refresh or a shared link keeps them." Same flat shape, same repeated
 * keys, same one-parser rule — and one deliberate difference, below, which is the whole reason this is
 * a separate module rather than a generalisation of that one.
 *
 * `q` IS NOT IN THE URL, AND THAT IS THE DIFFERENCE. The endpoint accepts it and the pipeline writes
 * its own search term — but `q` here searches `verbatim_text`, the lender's words about a borrower's
 * file. A shared link would carry "earnest money deposit in the amount of $2,850.00" or an employer's
 * name into whatever the recipient pastes it into, and into their browser history (ADR-405 as amended:
 * "a filter that matches NPI stays out of the shareable URL"). So the search box holds its term in
 * component state, every other filter is shareable, and `test_the_search_term_never_reaches_the_url`
 * is what keeps that true rather than this paragraph.
 *
 * The pipeline has the same exposure through borrower-name search and is recorded as such in the
 * survey; it is not fixed here, because one ticket quietly changing another screen's URL contract is
 * how a saved view breaks.
 *
 * UNKNOWN VALUES ARE FILTERED, NEVER CAST, for the reason `readPipelineUrl` gives: the endpoint types
 * these as enums, so an unrecognised one is a 422 and a blank screen. A URL is a paste-able,
 * bookmarkable artifact — a typo in one should drop that filter and show more, not break the page —
 * and the day a status is retired, every bookmark carrying it widens instead of failing.
 */
"use client";

import { OWNER_LABEL } from "@/lib/conditions/owners";
import { CONDITION_LENDER_STATUS, CONDITION_PREP_STATUS } from "@/lib/status";
import { BUCKET_KIND_CHIP } from "@/lib/types/conditions";
import type {
  BucketKind,
  ConditionLenderStatus,
  ConditionPrepStatus,
  OwnerHint,
} from "@/lib/types/conditions";
import { useSearchParams } from "next/navigation";
import { useMemo } from "react";

/** How the list is grouped. Sheet order inside every group, always. */
export type ConditionGroupBy = "heading" | "owner" | "prep_status";

export interface ConditionListUrlState {
  roundNumber: number | null;
  lenderStatus: ConditionLenderStatus[];
  prepStatus: ConditionPrepStatus[];
  owner: OwnerHint[];
  bucketKind: BucketKind[];
  groupBy: ConditionGroupBy;
}

export const EMPTY_LIST_URL_STATE: ConditionListUrlState = {
  roundNumber: null,
  lenderStatus: [],
  prepStatus: [],
  owner: [],
  bucketKind: [],
  groupBy: "heading",
};

// The membership tests read the vocabularies that are ALREADY exhaustive over each union — the status
// maps from `lib/status.ts`, the chip map for headings, the owner labels. Not a second list of
// members: a second list is how the two drift, and the cross-stack mirror only guards the types.
const isPrepStatus = (v: string): v is ConditionPrepStatus =>
  Object.hasOwn(CONDITION_PREP_STATUS, v);
const isLenderStatus = (v: string): v is ConditionLenderStatus =>
  Object.hasOwn(CONDITION_LENDER_STATUS, v);
const isBucketKind = (v: string): v is BucketKind => Object.hasOwn(BUCKET_KIND_CHIP, v);
const isOwner = (v: string): v is OwnerHint => Object.hasOwn(OWNER_LABEL, v);

const isGroupBy = (v: string | null): v is ConditionGroupBy =>
  v === "heading" || v === "owner" || v === "prep_status";

/** Read filter state out of a `URLSearchParams`. Unknown keys and values are ignored. */
export function readConditionListUrl(params: URLSearchParams): ConditionListUrlState {
  const round = Number(params.get("round"));
  return {
    // A round is a POSITIVE INTEGER or nothing. `Number("")` is 0 and `Number("two")` is NaN, and
    // both would otherwise become a filter for round 0 — which matches no sheet and empties the list.
    roundNumber: Number.isInteger(round) && round > 0 ? round : null,
    lenderStatus: params.getAll("lender_status").filter(isLenderStatus),
    prepStatus: params.getAll("prep_status").filter(isPrepStatus),
    owner: params.getAll("owner").filter(isOwner),
    bucketKind: params.getAll("bucket_kind").filter(isBucketKind),
    groupBy: isGroupBy(params.get("group")) ? (params.get("group") as ConditionGroupBy) : "heading",
  };
}

/**
 * The parsed URL state, memoised — the ONE place that reads it.
 *
 * The list, the filter row, the summary bar and the empty state all need it, and four parsers of one
 * source is four chances to disagree about what is filtered. `usePipelineUrl` says the same thing
 * about two.
 */
export function useConditionListUrl(): ConditionListUrlState {
  const searchParams = useSearchParams();
  const query = searchParams.toString();
  return useMemo(() => readConditionListUrl(new URLSearchParams(query)), [query]);
}

/**
 * Serialise filter state to a query string.
 *
 * Empty values are omitted rather than written as blanks, and the DEFAULT grouping is omitted too:
 * `?group=heading` and no `group` mean the same thing, and only one of them survives a copy-paste
 * looking like what the processor actually did.
 */
export function writeConditionListUrl(state: ConditionListUrlState): string {
  const params = new URLSearchParams();
  if (state.roundNumber !== null) params.set("round", String(state.roundNumber));
  for (const value of state.lenderStatus) params.append("lender_status", value);
  for (const value of state.prepStatus) params.append("prep_status", value);
  for (const value of state.owner) params.append("owner", value);
  for (const value of state.bucketKind) params.append("bucket_kind", value);
  if (state.groupBy !== "heading") params.set("group", state.groupBy);
  const query = params.toString();
  return query ? `?${query}` : "";
}

/**
 * True when anything is filtered — what chooses between "no conditions yet" and "no matches".
 *
 * GROUPING IS NOT A FILTER and is excluded on purpose: regrouping hides nothing, so a list that is
 * empty while grouped by owner is empty for some other reason, and offering "Clear filters" there
 * would point a processor at the wrong control.
 *
 * `q` IS A FILTER EVEN THOUGH IT IS NOT IN THE URL, so the caller passes it in. The empty state has to
 * say "nothing matches *invoice*" when the only active filter is the search term, and a helper that
 * read the URL alone would call that state "nothing yet".
 */
export function isConditionListFiltered(state: ConditionListUrlState, search = ""): boolean {
  return (
    state.roundNumber !== null ||
    state.lenderStatus.length > 0 ||
    state.prepStatus.length > 0 ||
    state.owner.length > 0 ||
    state.bucketKind.length > 0 ||
    search.trim() !== ""
  );
}

/**
 * The active filters in a processor's words, for S2-09's "No open condition is waiting on Insurance".
 *
 * NAMED, NOT COUNTED. `EmptyState kind="filtered"` requires the filter to be named — "Nothing in
 * Blocked to submit matches ellis" tells a processor what to undo, "No results" tells them nothing —
 * and these labels come from the same vocabularies the chips and controls use, so the sentence and the
 * control a processor reaches for agree on the words.
 */
export function describeConditionFilters(state: ConditionListUrlState, search = ""): string[] {
  const parts: string[] = [];
  if (state.roundNumber !== null) parts.push(`Round ${state.roundNumber}`);
  for (const value of state.prepStatus)
    parts.push(`Our status: ${CONDITION_PREP_STATUS[value].label}`);
  for (const value of state.lenderStatus)
    parts.push(`Lender: ${CONDITION_LENDER_STATUS[value].label}`);
  // "Owner not known", NOT `Owner: ${OWNER_LABEL.unknown}`. The shared label is "Not known", because
  // that is what the chip draws on S2-01/02/03, where the column heading already supplies the word
  // "Owner". Here the phrase stands alone inside a sentence, and "Owner: Not known" reads as a
  // lookup rather than a fact while a bare "Not known" says nothing about WHAT is not known. The two
  // places need different words for one fact, which is why this is not simply the label.
  for (const value of state.owner) {
    parts.push(value === "unknown" ? "Owner not known" : `Owner: ${OWNER_LABEL[value]}`);
  }
  for (const value of state.bucketKind) parts.push(`Heading: ${BUCKET_KIND_CHIP[value]}`);
  // The term itself, quoted, because the processor typed it and it is the filter they will undo
  // first. Safe on screen — it is the URL this must stay out of, not the page.
  if (search.trim() !== "") parts.push(`matching “${search.trim()}”`);
  return parts;
}
