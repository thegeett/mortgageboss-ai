/**
 * Condition rounds and conditions (LP-909).
 *
 * THE ROUND IS THE UNIT OF CACHE, NOT THE CONDITION. Every write here changes a round AND may change
 * the file's conditions — an import turns rows into conditions, an enrich adds some to an existing
 * round — so the invalidations below name both lists. A processor who imports and then does not see
 * the conditions appear will import again.
 *
 * THE POLL IS ON `status`, NEVER ON THE PRESENCE OF ROWS. A `parsing` round carries the
 * rules-read rows too (see `ConditionRound.draft_rows`), so "has rows" would stop the poll while the
 * AI split was still running and show S1-02's skeletons as though they were reviewable. S1-02's
 * requirement is literally "poll until `DRAFT` or `PARSE_FAILED`".
 */
import { apiClient } from "@/lib/api/client";
import type {
  AddConditionInput,
  BucketKind,
  BulkInput,
  BulkResult,
  Condition,
  ConditionDetail,
  ConditionEnrichResult,
  ConditionEvent,
  ConditionImportResult,
  ConditionLenderStatus,
  ConditionOrigin,
  ConditionPrepStatus,
  ConditionRound,
  ConditionRoundCompleteness,
  ConditionSort,
  ConditionSummary,
  DraftUpdateInput,
  OwnerHint,
  OwnerInput,
  PasteConditionsInput,
  PrepStatusInput,
  ReopenInput,
  VerdictInput,
} from "@/lib/types/conditions";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

const API_V1 = "/api/v1";

/** How often to re-ask while a round is being read. */
const PARSE_POLL_MS = 2_000;

export const conditionRoundsQueryKey = (fileId: string) => ["condition-rounds", fileId] as const;
export const conditionRoundQueryKey = (roundId: string) => ["condition-round", roundId] as const;
export const conditionsQueryKey = (fileId: string, params?: ConditionListParams) =>
  ["conditions", fileId, params ?? {}] as const;
export const conditionsSummaryQueryKey = (fileId: string) =>
  ["conditions-summary", fileId] as const;
export const conditionQueryKey = (conditionId: string) => ["condition", conditionId] as const;
export const conditionEventsQueryKey = (conditionId: string) =>
  ["condition-events", conditionId] as const;
export const conditionRoundEventsQueryKey = (roundId: string) =>
  ["condition-round-events", roundId] as const;

const filePath = (fileId: string) => `${API_V1}/loan-files/${fileId}`;
const roundPath = (roundId: string) => `${API_V1}/condition-rounds/${roundId}`;

/**
 * How long a round may sit in `parsing` before we stop asking, and before the server will accept a
 * reparse.
 *
 * THIS NUMBER IS THE SERVER'S, AND THE VERSION THIS REPLACED WAS WRONG IN THE DANGEROUS
 * DIRECTION. It was `5 * 60 * 1000`, justified by S1-02's "usually under 30 seconds" — a sentence
 * about the HEALTHY case, which is not what a bound is for. It consulted neither Celery limit.
 *
 * 300 seconds is not merely below the parse timeout: it is EXACTLY `PARSE_SOFT_LIMIT_SECONDS`, so
 * the tab declared a round dead at the precise instant the worker raises `SoftTimeLimitExceeded` —
 * with 60 seconds of hard-limit runway left in which the task can still finish, or settle
 * `parse_failed` itself with a reason a processor can act on. Offering "Try again" there would have
 * raced a live worker rather than rescued a stuck one, and the server now REFUSES a reparse inside
 * its own window, so the old value would have produced a button that reliably 409s.
 *
 * It is `STRANDED_AFTER_SECONDS` from `backend/app/conditions/limits.py`, where it is derived as
 * `PARSE_HARD_LIMIT_SECONDS + a grace` rather than written as a literal. `tests/test_condition_type_mirror.py`
 * pins these two together, the same way it pins `MAX_PASTE_CHARS` — a number both sides enforce has
 * to be one number, and the 20 MB ceiling is the cautionary case that still lacks such a pin.
 */
const STRANDED_AFTER_MS = 600 * 1000;

/** True while the server says it is still reading this round. */
export function isBeingRead(round: ConditionRound): boolean {
  return round.status === "parsing";
}

/**
 * A round that has been `parsing` for longer than anything could legitimately take.
 *
 * THIS STATE IS REAL AND THE BACKEND DOCUMENTS IT AS UNMITIGATED. A round is committed in
 * `parsing` BEFORE the task is enqueued — correctly, since a worker that picked it up first would
 * find no row — so a broker that is down leaves a round nothing will ever move.
 * `_enqueue_split_or_fail` guards the paste door and says of the upload door, in as many words:
 * "UNGUARDED, AND THAT IS A DECISION RATHER THAN AN OVERSIGHT … a broker that is down strands it".
 * Forward is unguarded too.
 *
 * So "poll until DRAFT or PARSE_FAILED" (S1-02) has a third outcome the spec does not contemplate:
 * never. Without this the tab asks every two seconds for as long as it stays open.
 */
export function isStranded(round: ConditionRound): boolean {
  if (!isBeingRead(round)) return false;
  const started = Date.parse(round.created_at);
  // An unparseable timestamp stops the polling rather than starting it. Failing towards "stop" is
  // the safe direction: the cost is a processor pressing refresh, where the other direction is a
  // request every two seconds forever on a date we could not read.
  if (Number.isNaN(started)) return true;
  return Date.now() - started > STRANDED_AFTER_MS;
}

/**
 * Whether asking again could still change the answer.
 *
 * BOUNDED ON `created_at`, NOT ON A COUNT OF INTERVALS, and the difference is what makes it a
 * bound at all. A counter lives in the query's session: reopening the tab on a round stranded
 * yesterday starts a fresh count and polls forever again — the same defect wearing a ceiling. Asking
 * how old the round is means a stale stranded round is polled ZERO times on a fresh tab.
 */
export function isWorthPolling(round: ConditionRound): boolean {
  return isBeingRead(round) && !isStranded(round);
}

/**
 * Whether any arrival on this round stored bytes.
 *
 * IT ASKS THE SERVER'S OWN QUESTION NOW, AND IT USED TO ASK A PROXY (LP-909 review). The authority
 * is `has_stored_sheet` in `services/condition_rounds.py`, which keys on `storage_path` and says
 * why: "it is the BYTES that make a second attach meaningless. `kind` would need a list of three
 * values kept in step with the enum." This function WAS that list, and could not be anything else
 * while `ConditionSourcePublic` did not serialise the path — the client was structurally unable to
 * ask the real question, so it asked the nearest one it could see.
 *
 * It held only because every bytes-carrying source happens to be written as `pdf_upload` or `email`.
 * That is a fact about the current writers rather than a rule binding them: a fourth kind that
 * stores bytes, or a bytes-less forward, split the two answers apart silently, and the failure was a
 * button offered for a merge the server refuses.
 *
 * `has_bytes` is now on every source — a boolean rather than the path itself, because
 * `_storage_path` is server-controlled precisely so a sender's filename never shapes the storage
 * layout, and shipping it would export that layout to answer yes or no.
 *
 * Still read across the LIST, because `sources` is a list: a paste that gained a PDF carries both
 * arrivals, and the question is whether bytes are present anywhere, not how the round began.
 *
 * IT LIVES HERE RATHER THAN IN `round-strip.tsx` BECAUSE A THIRD FEATURE NOW ASKS IT. S1-13's
 * attach-or-new question is raised from the Communication tab, and a communication component
 * reaching into a conditions PRESENTATION module for a predicate is the wrong direction. This file
 * already holds `isBeingRead`, `isStranded` and `isWorthPolling` — the same category of question
 * about the same row.
 *
 * (The server-side name in the paragraph above changed too: `_has_pdf_source` in
 * `condition_enrich.py` was folded into `has_stored_sheet` when three copies of that one rule were
 * collapsed, so this comment named a function that no longer existed.)
 */
export function hasPdf(round: ConditionRound): boolean {
  return round.sources.some((source) => source.has_bytes);
}

/**
 * Whether the server would accept a PDF for this round.
 *
 * THE SERVER REFUSES ON TWO COUNTS AND THE STRIP CHECKED ONE (LP-909 review).
 * `enrich_round_with_pdf` raises `RoundNotEnrichable` when the status is outside `ENRICHABLE`
 * (`draft` or `imported`) AND when the round already has stored bytes. Gating on the second alone
 * offered "Attach the lender's PDF" on a `discarded` round — which the strip renders deliberately,
 * at `opacity-60`, so the button appeared on it — and on a `parse_failed` one. Both answer 409.
 *
 * A control that offers what the server refuses is the same defect as a label promising what its
 * handler cannot do; this stage has corrected that three times already.
 */
export function canAttachPdf(round: ConditionRound): boolean {
  const enrichable = round.status === "draft" || round.status === "imported";
  return enrichable && !hasPdf(round);
}

// --- reads ------------------------------------------------------------------ //

export async function fetchConditionRounds(fileId: string): Promise<ConditionRound[]> {
  return (await apiClient.get<ConditionRound[]>(`${filePath(fileId)}/condition-rounds`)).data;
}

/**
 * The file's rounds, newest first — the round strip (S1-05) and the empty state's emptiness.
 *
 * Polls while some round is worth polling, and the ceiling is the point.
 *
 * AN EARLIER VERSION OF THIS COMMENT SAID IT "STOPS BY ITSELF: the round settling to `draft` or
 * `parse_failed` is what ends it" — which asserts a guarantee this codebase explicitly documents as
 * absent. A stranded round never settles, so that sentence described a loop with no exit while
 * claiming the opposite. See `isStranded`; raised in review.
 *
 * DISCARDED ROUNDS ARE IN THIS LIST, deliberately — a processor who threw a draft away should
 * see that they did, and a round silently vanishing reads as data loss. The UI filters on `status`.
 */
export function useConditionRounds(fileId: string) {
  return useQuery({
    queryKey: conditionRoundsQueryKey(fileId),
    queryFn: () => fetchConditionRounds(fileId),
    enabled: Boolean(fileId),
    refetchInterval: (query) =>
      (query.state.data ?? []).some(isWorthPolling) ? PARSE_POLL_MS : false,
  });
}

export async function fetchConditionRound(roundId: string): Promise<ConditionRound> {
  return (await apiClient.get<ConditionRound>(roundPath(roundId))).data;
}

/** One round — the review screen (S1-04/07/10/11) and the round-details sheet (S1-09). */
export function useConditionRound(roundId: string | null) {
  return useQuery({
    queryKey: conditionRoundQueryKey(roundId ?? ""),
    queryFn: () => fetchConditionRound(roundId as string),
    enabled: Boolean(roundId),
    refetchInterval: (query) =>
      query.state.data && isWorthPolling(query.state.data) ? PARSE_POLL_MS : false,
  });
}

export async function fetchRoundEvents(roundId: string): Promise<ConditionEvent[]> {
  return (await apiClient.get<ConditionEvent[]>(`${roundPath(roundId)}/events`)).data;
}

/**
 * One round's history, oldest first — the History section of the round-details sheet (S1-09).
 *
 * NOT POLLED, AND NOT PART OF THE ROUND. `condition_events` is APPEND-ONLY, so a history cannot
 * change under a reader except by something else on this screen writing — and every such write
 * already invalidates through `invalidateRound`. Polling it would ask a question whose answer only
 * changes when we change it.
 *
 * FETCHED SEPARATELY RATHER THAN EMBEDDED IN THE ROUND, because the round is fetched constantly —
 * the strip, the dashboard, every mutation's invalidation — and the history is read only when a
 * processor opens one sheet. Attaching it to `ConditionRoundPublic` would put a second query behind
 * every round read on the tab to serve a panel almost nobody has open.
 */
export function useRoundEvents(roundId: string | null) {
  return useQuery({
    queryKey: conditionRoundEventsQueryKey(roundId ?? ""),
    queryFn: () => fetchRoundEvents(roundId as string),
    enabled: Boolean(roundId),
  });
}

/**
 * EVERY `conditions` QUERY FOR ONE FILE, whatever its filters — what an invalidation must name.
 *
 * `conditionsQueryKey` carries the params so two filter sets are two caches, and an invalidation
 * must reach all of them. Every write invalidates this two-element prefix, which says so on its face.
 * (The full key would ALSO reach them today — TanStack matches `{}` against any params object — but
 * that is a property of an empty object nobody reading the call would rely on. An earlier version of
 * this comment said the full key matched only the unfiltered list; review checked
 * `partialMatchKey` and that was wrong.)
 */
export const conditionsQueryPrefix = (fileId: string) => ["conditions", fileId] as const;

const conditionPath = (conditionId: string) => `${API_V1}/conditions/${conditionId}`;

/**
 * The filters and the sort the list reads (LP-911). Every field is optional, and a call with none
 * gets Stage 1's response unchanged — which is a Done-when of that ticket, not a courtesy.
 *
 * ARRAYS MUST SERIALISE AS REPEATED KEYS, AND AXIOS DOES NOT DO THAT BY DEFAULT. FastAPI reads
 * `?owner=borrower&owner=title`; axios 1.x writes `owner[]=borrower` unless told otherwise, and
 * FastAPI ignores that — so the filter would silently do nothing and the list would come back
 * unfiltered, which looks like a backend bug from the screen. `paramsSerializer: { indexes: null }`
 * is what produces the repeated form.
 */
export interface ConditionListParams {
  round?: number;
  lender_status?: ConditionLenderStatus[];
  prep_status?: ConditionPrepStatus[];
  owner?: OwnerHint[];
  bucket_kind?: BucketKind[];
  lender_code?: string;
  category?: string;
  info_only?: boolean;
  origin?: ConditionOrigin;
  q?: string;
  sort?: ConditionSort;
}

/**
 * The list, and whether the server had more to give.
 *
 * A PAIR RATHER THAN A BARE ARRAY, BECAUSE THE CAP IS REPORTED IN A HEADER. `MAX_CONDITIONS` is 500
 * and the endpoint sets `X-Conditions-Capped: true` when it hit that — in a header, because the
 * response body's shape is a Done-when of LP-911 and could not grow a wrapper. `fetchConditions`
 * returned `.data` and dropped the header on the floor, so **a truncated list rendered as a complete
 * one**: the exact failure the cap exists to make visible. Raised in LP-911's review and carried
 * forward to here.
 */
export interface ConditionListPage {
  rows: Condition[];
  /** True when the server stopped at its ceiling. The list says so rather than implying completeness. */
  capped: boolean;
}

export async function fetchConditions(
  fileId: string,
  params: ConditionListParams = {},
): Promise<ConditionListPage> {
  const response = await apiClient.get<Condition[]>(`${filePath(fileId)}/conditions`, {
    params,
    paramsSerializer: { indexes: null },
  });
  // LOWERCASED, AND ONLY READABLE BECAUSE THE API NAMES IT IN `expose_headers`. A browser reads no
  // custom response header across origins otherwise — `page-image.ts` carries the same note, having
  // had width and height silently read back as 0 for a whole ticket. Header values are strings, so
  // this compares against "true" rather than trusting truthiness: the string "false" is truthy.
  const capped = String(response.headers["x-conditions-capped"] ?? "").toLowerCase() === "true";
  return { rows: response.data, capped };
}

/**
 * The file's conditions, filtered and sorted — the list (S2-01, S2-02).
 *
 * THE PARAMS ARE PART OF THE QUERY KEY. Without that, changing a filter would serve the previous
 * filter's rows from cache until a refetch landed, so the screen would show a list that does not
 * match the filter row above it.
 *
 * IT RETURNS A PAGE, NOT AN ARRAY. One hook answering "what are the rows, and were there more" beats
 * a second hook for the cap: two hooks asking one question is how the two come to disagree, which is
 * the argument `resolve_user_names` and `usePipelineUrl` both make in their own docstrings.
 */
export function useConditions(fileId: string, params: ConditionListParams = {}) {
  return useQuery({
    queryKey: conditionsQueryKey(fileId, params),
    queryFn: () => fetchConditions(fileId, params),
    enabled: Boolean(fileId),
  });
}

export async function fetchConditionsSummary(fileId: string): Promise<ConditionSummary> {
  return (await apiClient.get<ConditionSummary>(`${filePath(fileId)}/conditions/summary`)).data;
}

/**
 * The counts for the summary bar and the file rail (S2-01, S2-02).
 *
 * NOT FILTERED, DELIBERATELY. The bar's numbers are what the filters are applied TO — each one is a
 * filter a processor can click — so recomputing them under the current filter would make every number
 * describe the view instead of the file, and "Open 6" would change when you clicked it.
 */
export function useConditionsSummary(fileId: string) {
  return useQuery({
    queryKey: conditionsSummaryQueryKey(fileId),
    queryFn: () => fetchConditionsSummary(fileId),
    enabled: Boolean(fileId),
  });
}

export async function fetchCondition(conditionId: string): Promise<ConditionDetail> {
  return (await apiClient.get<ConditionDetail>(conditionPath(conditionId))).data;
}

/** One condition with every round it did or did not appear on — the detail sheet (S2-03). */
export function useCondition(conditionId: string | null) {
  return useQuery({
    queryKey: conditionQueryKey(conditionId ?? ""),
    queryFn: () => fetchCondition(conditionId as string),
    enabled: Boolean(conditionId),
  });
}

export async function fetchConditionEvents(conditionId: string): Promise<ConditionEvent[]> {
  return (await apiClient.get<ConditionEvent[]>(`${conditionPath(conditionId)}/events`)).data;
}

/**
 * One condition's history, newest first — the detail sheet's History (S2-03).
 *
 * FETCHED SEPARATELY AND NOT POLLED, for the reason `useRoundEvents` gives: `condition_events` is
 * append-only, so the history cannot change under a reader except by something on this screen
 * writing — and the condition itself is refetched on every list refresh, where the history is read
 * only when somebody opens one sheet.
 */
export function useConditionEvents(conditionId: string | null) {
  return useQuery({
    queryKey: conditionEventsQueryKey(conditionId ?? ""),
    queryFn: () => fetchConditionEvents(conditionId as string),
    enabled: Boolean(conditionId),
  });
}

// --- writes ----------------------------------------------------------------- //

/**
 * Everything a round write can change.
 *
 * Named once rather than repeated per mutation, because a set that has to be remembered six times
 * is a set that will differ in one of them — and it did. `useAddCondition` called this without a
 * round id, so the round-details sheet (S1-09) kept a stale `condition_count` after a condition was
 * typed into that round. Found in review, and the id was sitting in the response the whole time.
 *
 * `loan-file-activity` is here because the import writes a timeline entry.
 */
function invalidateRound(
  queryClient: ReturnType<typeof useQueryClient>,
  fileId: string,
  roundId?: string,
) {
  void queryClient.invalidateQueries({ queryKey: conditionRoundsQueryKey(fileId) });
  // THE PREFIX, NOT THE FULL KEY — see `conditionsQueryPrefix`.
  void queryClient.invalidateQueries({ queryKey: conditionsQueryPrefix(fileId) });
  // AN OPEN DETAIL SHEET MOVES WITH THEM (LP-911 review). An import adds a round pill and a "seen
  // again" line to every condition it touched, and these keys are per condition rather than per
  // file, so the whole family is invalidated rather than guessing which ids the import reached.
  void queryClient.invalidateQueries({ queryKey: ["condition"] });
  void queryClient.invalidateQueries({ queryKey: ["condition-events"] });
  // THE SUMMARY MOVES WHENEVER THE CONDITIONS DO. An import changes every count on the bar, and a
  // processor who imports and sees the numbers unchanged will import again — the same reasoning this
  // function's own docstring gives for invalidating both lists rather than one.
  void queryClient.invalidateQueries({ queryKey: conditionsSummaryQueryKey(fileId) });
  void queryClient.invalidateQueries({ queryKey: ["loan-file-activity", fileId] });
  if (roundId) {
    void queryClient.invalidateQueries({ queryKey: conditionRoundQueryKey(roundId) });
  }
}

export interface UploadSheetInput {
  file: File;
  completeness: ConditionRoundCompleteness;
}

/**
 * Upload the lender's PDF → a `parsing` round, read in the background (202).
 *
 * `completeness` defaults to "full" at the call site, not here: a processor uploading the lender's
 * letter is giving us the whole list unless they say otherwise (S1-04's toggle defaults to
 * *Full list* for a PDF).
 */
export function useUploadConditionSheet(fileId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ file, completeness }: UploadSheetInput) => {
      const form = new FormData();
      form.append("file", file);
      form.append("completeness", completeness);
      return (
        await apiClient.post<ConditionRound>(`${filePath(fileId)}/condition-rounds/uploads`, form, {
          headers: { "Content-Type": "multipart/form-data" },
        })
      ).data;
    },
    onSuccess: (round) => invalidateRound(queryClient, fileId, round.id),
  });
}

/** Paste from the lender's portal → a round holding what the rules read (201, S1-06). */
export function usePasteConditions(fileId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: PasteConditionsInput) =>
      (await apiClient.post<ConditionRound>(`${filePath(fileId)}/condition-rounds/paste`, input))
        .data,
    onSuccess: (round) => invalidateRound(queryClient, fileId, round.id),
  });
}

/**
 * Read a stored sheet again — S1-03's "Try again" and S1-02's stranded state (200).
 *
 * THIS HOOK IS WHY TWO SCREENS MAY FINALLY OFFER THE BUTTON THEY ALREADY DESCRIBED. `RoundFailed`
 * and `RoundReading` both took `onRetry` optionally and the dashboard passed none, because no route
 * re-read an existing round — `parse_condition_round.delay()` was called from creation paths only.
 * The comments saying so were correct when written and are now false; they have been corrected
 * rather than left to mislead.
 *
 * IT CAN LEGITIMATELY 409, AND THE CALLER MUST SHOW THE REASON RATHER THAN SWALLOW IT. The server
 * refuses a round it is still reading (inside the stranded window), a draft, an imported round, a
 * discarded one, and a round whose only source was a paste and so has no PDF to re-read. Each
 * carries its own sentence, and "it was pasted, there is nothing stored to read again" tells a
 * processor something entirely different from "it is still being read".
 *
 * NO REQUEST BODY. The endpoint takes no options, so there is nothing to send — and unlike
 * `documents.py`'s reprocess it declares no Pydantic body at all, so a body-less POST is what it
 * expects rather than a 422.
 */
export function useReparseRound(fileId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (roundId: string) =>
      (await apiClient.post<ConditionRound>(`${roundPath(roundId)}/reparse`)).data,
    // The round goes back to `parsing`, so the list must refetch for the polling to resume — the
    // reparse is invisible without this even though the request succeeded.
    onSuccess: (round) => invalidateRound(queryClient, fileId, round.id),
  });
}

/**
 * Turn a reviewed draft into the file's conditions (200, not 201).
 *
 * The round already existed and is settled in place, from `draft` to `imported`; nothing new is
 * addressable afterwards that was not before.
 */
export function useImportRound(fileId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (roundId: string) =>
      (await apiClient.post<ConditionImportResult>(`${roundPath(roundId)}/import`, {})).data,
    onSuccess: (result) => invalidateRound(queryClient, fileId, result.round_id),
  });
}

/**
 * Throw a draft away. It stays on the strip, marked discarded.
 *
 * An IMPORTED round is refused with 409: its conditions survive (ADR-404) and it keeps its number,
 * so "discarded" would mean one thing for a draft and another for an imported round.
 */
export function useDiscardRound(fileId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (roundId: string) =>
      (await apiClient.post<ConditionRound>(`${roundPath(roundId)}/discard`, {})).data,
    onSuccess: (round) => invalidateRound(queryClient, fileId, round.id),
  });
}

export interface UpdateDraftInput extends DraftUpdateInput {
  roundId: string;
}

/**
 * Replace a draft's rows before import (S1-04's editing).
 *
 * WHAT IS SENT IS WHAT IMPORTS. The fingerprint is taken of the edited text, so an edited row may
 * match a different condition or none — correct rather than unfortunate, and the spec's own frontend
 * test is "editing a row and importing sends the edited text".
 */
export function useUpdateDraft(fileId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ roundId, ...body }: UpdateDraftInput) =>
      (await apiClient.put<ConditionRound>(`${roundPath(roundId)}/draft`, body)).data,
    onSuccess: (round) => invalidateRound(queryClient, fileId, round.id),
  });
}

/**
 * Add one condition by hand (201, S1-12).
 *
 * It goes into the latest imported round, or opens round 1 with source `manual` if the file has
 * none — so its `R1` chip names the round it was filed into rather than a sheet it was printed on.
 * `origin` is what keeps those distinguishable.
 *
 * THE ROUND IT JOINED MUST BE INVALIDATED TOO, and this called `invalidateRound` without an id.
 * A hand-typed condition changes that round's `condition_count`, which is exactly what the
 * round-details sheet (S1-09) displays — so with the sheet open, adding a condition left the count
 * stale. `last_seen_round_id` is the round it was filed into and was in the response all along.
 */
export function useAddCondition(fileId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: AddConditionInput) =>
      (await apiClient.post<Condition>(`${filePath(fileId)}/conditions`, input)).data,
    onSuccess: (condition) => invalidateRound(queryClient, fileId, condition.last_seen_round_id),
  });
}

/**
 * Everything ONE condition's write can change (LP-912).
 *
 * NARROWER THAN `invalidateRound` ON PURPOSE. A status move does not touch the round strip, the
 * round's own card, or the file's activity timeline, and invalidating those would refetch the whole
 * tab on every click of a status control. What it does change is the row, the summary bar's counts,
 * and — if a sheet is open on this condition — its detail and its history.
 *
 * THE SUMMARY IS NOT OPTIONAL HERE. Every count on S2-01's bar is derived from status, so a processor
 * who marks a condition cleared and sees "Open 6" unchanged has been shown a stale number about the
 * exact thing they just did.
 */
function invalidateCondition(
  queryClient: ReturnType<typeof useQueryClient>,
  fileId: string,
  conditionId: string,
) {
  void queryClient.invalidateQueries({ queryKey: conditionsQueryPrefix(fileId) });
  void queryClient.invalidateQueries({ queryKey: conditionsSummaryQueryKey(fileId) });
  void queryClient.invalidateQueries({ queryKey: conditionQueryKey(conditionId) });
  void queryClient.invalidateQueries({ queryKey: conditionEventsQueryKey(conditionId) });
}

/** Move our preparation track (S2-05). */
export function usePrepStatus(fileId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ conditionId, ...body }: { conditionId: string } & PrepStatusInput) =>
      (await apiClient.post<Condition>(`${conditionPath(conditionId)}/prep-status`, body)).data,
    onSuccess: (condition) => invalidateCondition(queryClient, fileId, condition.id),
  });
}

/**
 * Record what the lender said — the only way to `cleared` or `waived` (S2-06, ADR-404).
 *
 * IT CAN LEGITIMATELY 409 AND THE CALLER MUST SHOW THE SENTENCE. A derived source without its round
 * is refused, and so is a stale write; each carries its own wording, and "Someone else changed this
 * condition" tells a processor something entirely different from a missing round.
 */
export function useVerdict(fileId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ conditionId, ...body }: { conditionId: string } & VerdictInput) =>
      (await apiClient.post<Condition>(`${conditionPath(conditionId)}/verdict`, body)).data,
    onSuccess: (condition) => invalidateCondition(queryClient, fileId, condition.id),
  });
}

/** Undo a verdict — a misclick, or the lender re-issuing. The old verdict stays in the history. */
export function useReopen(fileId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ conditionId, ...body }: { conditionId: string } & ReopenInput) =>
      (await apiClient.post<Condition>(`${conditionPath(conditionId)}/reopen`, body)).data,
    onSuccess: (condition) => invalidateCondition(queryClient, fileId, condition.id),
  });
}

/** Set or clear who it is waiting on (S2-04). PUT, because it replaces one value. */
export function useOwner(fileId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ conditionId, ...body }: { conditionId: string } & OwnerInput) =>
      (await apiClient.put<Condition>(`${conditionPath(conditionId)}/owner`, body)).data,
    onSuccess: (condition) => invalidateCondition(queryClient, fileId, condition.id),
  });
}

/**
 * One write applied to many conditions (S2-07). 200 even when it refused rows.
 *
 * REFUSALS ARE IN THE BODY, NOT IN AN ERROR, so `onSuccess` runs for a partly-applied write and the
 * caller must read `refused` rather than assume everything moved. A dialog that closed on success
 * without reading it would tell a processor eleven rows were cleared when one was skipped.
 *
 * IT INVALIDATES THE WHOLE CONDITION AND HISTORY FAMILIES rather than each id it touched: the request
 * carries up to 500 ids, and any of their sheets may be open.
 */
export function useBulkConditions(fileId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: BulkInput) =>
      (await apiClient.post<BulkResult>(`${filePath(fileId)}/conditions/bulk`, input)).data,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: conditionsQueryPrefix(fileId) });
      void queryClient.invalidateQueries({ queryKey: conditionsSummaryQueryKey(fileId) });
      void queryClient.invalidateQueries({ queryKey: ["condition"] });
      void queryClient.invalidateQueries({ queryKey: ["condition-events"] });
    },
  });
}

export interface AttachPdfInput {
  roundId: string;
  file: File;
}

/**
 * Attach the lender's PDF to a round that was pasted → merge into THE SAME round (200, S1-09).
 *
 * Nothing is created: no second round, and — when the PDF carries the conditions the paste already
 * had — no new conditions either. The button appears only on a round with no PDF source.
 */
export function useAttachPdf(fileId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ roundId, file }: AttachPdfInput) => {
      const form = new FormData();
      form.append("file", file);
      return (
        await apiClient.post<ConditionEnrichResult>(`${roundPath(roundId)}/attach-pdf`, form, {
          headers: { "Content-Type": "multipart/form-data" },
        })
      ).data;
    },
    onSuccess: (result) => invalidateRound(queryClient, fileId, result.round_id),
  });
}
