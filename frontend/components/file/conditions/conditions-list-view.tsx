"use client";

import { ConfirmReadingFor } from "@/components/file/conditions/confirm-reading-dialog";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useDebouncedValue } from "@/hooks/use-debounced-value";
import type { ConditionListParams } from "@/lib/api/conditions";
import {
  useAddItem,
  useAttachPdf,
  useBulkConditions,
  useConditions,
  useConditionsSummary,
  useConfirmCleared,
  useOwner,
  usePrepStatus,
  useReopen,
  useResolveReworded,
  useSetNextStep,
  useSwitchCompleteness,
  useUpdateItem,
  useVerdict,
} from "@/lib/api/conditions";
import type { ConditionListUrlState } from "@/lib/conditions/list-url";
import { useConditionListUrl, writeConditionListUrl } from "@/lib/conditions/list-url";
import { getErrorMessage } from "@/lib/errors/api-error";
import { notifyError, notifySuccess } from "@/lib/toast";
import type {
  Condition,
  ConditionEnrichResult,
  ConditionPrepStatus,
  ConditionRound,
  OwnerHint,
} from "@/lib/types/conditions";
import { Info } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";
import { MoveBackDialog, RecordAnswerDialog } from "./condition-answer-dialogs";
import { ConditionDetailSheet } from "./condition-detail-sheet";
import { ConditionDraftDialog } from "./condition-draft-dialog";
import { ConditionPackagePanel } from "./condition-package-panel";
import { ConditionsBulkBar, bulkResultSummary } from "./conditions-bulk-bar";
import { ConditionsFilterRow } from "./conditions-filter-row";
import { ConditionsList } from "./conditions-list";
import { ConditionsSummaryBar } from "./conditions-summary-bar";
import { FiguresCheckPanel } from "./figures-check-panel";
import { ReadingStatus } from "./reading-status";
import { RoundComparisonPanel } from "./round-comparison-panel";
import { RoundDetailsSheet } from "./round-details-sheet";
import { RoundDrafts } from "./round-drafts";
import { RoundPlanPanel } from "./round-plan-panel";
import { RoundStrip } from "./round-strip";
import { WaitingOnDialog, waitingOnFor } from "./waiting-on-dialog";
import { WithdrawnSection } from "./withdraw-condition";

/**
 * The conditions list screen (S2-01, S2-02, S2-09) — LP-913.
 *
 * REPLACES `ImportedView` FOR AN IMPORTED ROUND. Stage 1's review, reading, failed and empty screens
 * are untouched: this is one branch of `ConditionsDashboard`, not a rewrite of the tab.
 *
 * TWO QUERIES, AND THE SECOND ONE IS NOT AN OVERSIGHT. The live list is filtered BY THE SERVER —
 * those filters are what LP-911 built and pinned ("open + owner=borrower returns exactly 7086 6132
 * 6637"), and not using them would strand that work and put a second, disagreeing implementation of
 * "what does owner=title mean" in the client. But the collapsed sections at the bottom must survive
 * the filters: S2-09 says in as many words that "the Cleared section is still shown below" when the
 * filters match nothing. One filtered query cannot answer both questions, so there is one of each.
 *
 * `q` GOES TO THE SERVER AND NEVER INTO THE URL. It is a server filter and `conditions_listed` logs
 * only the filter NAMES (LP-911 pins that with `structlog.testing.capture_logs`), so the term is not
 * recorded anywhere. What ADR-405's amendment governs is the SHAREABLE URL — a link carrying the
 * lender's wording — and `lib/conditions/list-url.ts` has no field that could serialise it.
 *
 * THE SHEET IS GIVEN THE ROWS THE LIST RENDERS, IN THAT ORDER, so Previous/Next follow the filter and
 * the grouping without the sheet knowing either exists.
 */
export function ConditionsListView({
  fileId,
  rounds,
  onPaste,
  onAddByHand,
  onUploadAnother,
}: {
  fileId: string;
  /** Every round on the file, newest first — the strip's own order. */
  rounds: ConditionRound[];
  onPaste: () => void;
  onAddByHand: () => void;
  onUploadAnother: () => void;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const urlState = useConditionListUrl();

  // THE SEARCH TERM LIVES HERE, NOT IN THE URL. See the module docstring.
  const [searchInput, setSearchInput] = useState("");
  const search = useDebouncedValue(searchInput, 300);

  const params: ConditionListParams = {
    round: urlState.roundNumber ?? undefined,
    lender_status: urlState.lenderStatus.length > 0 ? urlState.lenderStatus : undefined,
    prep_status: urlState.prepStatus.length > 0 ? urlState.prepStatus : undefined,
    owner: urlState.owner.length > 0 ? urlState.owner : undefined,
    bucket_kind: urlState.bucketKind.length > 0 ? urlState.bucketKind : undefined,
    next_step: urlState.step.length > 0 ? urlState.step : undefined,
    check: urlState.check ?? undefined,
    q: search.trim() === "" ? undefined : search.trim(),
  };

  const filtered = useConditions(fileId, params);
  const everything = useConditions(fileId, {});
  const summary = useConditionsSummary(fileId);
  const attach = useAttachPdf(fileId);

  const prepStatus = usePrepStatus(fileId);
  const owner = useOwner(fileId);
  const verdict = useVerdict(fileId);
  const reopen = useReopen(fileId);
  const bulk = useBulkConditions(fileId);
  const confirmCleared = useConfirmCleared(fileId);
  const resolveReworded = useResolveReworded(fileId);
  const switchCompleteness = useSwitchCompleteness(fileId);

  const [openRoundId, setOpenRoundId] = useState<string | null>(null);
  const [enrichment, setEnrichment] = useState<ConditionEnrichResult | null>(null);
  const [openConditionId, setOpenConditionId] = useState<string | null>(null);
  // S3-03 (LP-919): the condition whose reading she is confirming, opened from the detail sheet.
  // S3-01's "Add an item" (LP-920).
  const addItem = useAddItem(fileId);
  const setNextStep = useSetNextStep(fileId);
  const updateItem = useUpdateItem(fileId);
  const [confirmReadingId, setConfirmReadingId] = useState<string | null>(null);
  // LP-922 — the draft email open in S3-04's dialog, from a token, an item or the drafts line.
  const [draftId, setDraftId] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<ReadonlySet<string>>(new Set());
  const [answerFor, setAnswerFor] = useState<Condition[] | null>(null);
  const [moveBack, setMoveBack] = useState<{
    condition: Condition;
    to: ConditionPrepStatus | null;
    mode: "move-back" | "reopen";
  } | null>(null);
  const [refusal, setRefusal] = useState<string | null>(null);
  // LP-956 — a move to Waiting on a condition whose owner is her: who does it wait on?
  const [waitingAsk, setWaitingAsk] = useState<{
    condition: Condition;
    to: ConditionPrepStatus;
    reason?: string;
  } | null>(null);
  // HIDDEN BY ROUND ID, NOT BY A BOOLEAN. *Not now* and *Hide* dismiss the panel for the round she
  // dismissed; importing a newer sheet brings the new round's panel up rather than staying hidden
  // because she closed the previous one.
  const [hiddenPanelRoundId, setHiddenPanelRoundId] = useState<string | null>(null);
  const [panelRefusal, setPanelRefusal] = useState<string | null>(null);

  // The round whose plan S3-02 shows: the newest imported one (rounds come newest first).
  const newestImported = rounds.find((round) => round.status === "imported") ?? null;
  const openRound = rounds.find((round) => round.id === openRoundId) ?? null;
  const rows = filtered.data?.rows ?? [];
  const allRows = everything.data?.rows ?? [];
  const roundNumbers = rounds
    .filter((round) => round.round_number !== null && round.status === "imported")
    .map((round) => round.round_number as number);

  // THE NEWEST IMPORTED ROUND THAT WAS COMPARED. Round 1 carries no comparison — it was compared
  // against nothing — so on a one-round file there is no panel at all, which is correct rather than
  // an empty state.
  const importedAscending = rounds
    .filter((round) => round.status === "imported" && round.round_number !== null)
    .sort((a, b) => (a.round_number as number) - (b.round_number as number));
  const comparisonRound =
    [...importedAscending].reverse().find((round) => round.comparison !== null) ?? null;
  const previousRoundNumber =
    comparisonRound === null
      ? null
      : ([...importedAscending]
          .reverse()
          .find(
            (round) => (round.round_number as number) < (comparisonRound.round_number as number),
          )?.round_number ?? null);
  // THE ROUND THAT IS ASKING, NOT THE NEWEST ONE COMPARED (LP-915 review). They differ when a
  // partial round or a late older sheet follows a full one: the newest comparison suggests nothing,
  // and the full round's questions are still pending. At most one round is ever asking, because a
  // newer FULL comparison withdraws the older rounds' questions server-side.
  const suggestionRound =
    [...importedAscending]
      .reverse()
      .find((round) => (round.comparison?.probably_cleared.length ?? 0) > 0) ?? null;
  const suggestedIds = new Set(suggestionRound?.comparison?.probably_cleared ?? []);

  // The selection is by ID, so a row that a filter hides stays selected and still gets the bulk
  // action — which is what a processor who ticked it then narrowed the view would expect.
  const selected = allRows.filter((row) => selectedIds.has(row.id));

  function applyUrl(next: ConditionListUrlState) {
    // `replace`, not `push`: a filter click is not a place to go back to, and twelve of them would
    // bury the page a processor arrived from under twelve history entries.
    router.replace(`${pathname}${writeConditionListUrl(next)}`, { scroll: false });
  }

  /** Every write echoes the `updated_at` it read, so a stale one is refused rather than winning. */
  function movePrep(condition: Condition, to: ConditionPrepStatus) {
    const rank: Partial<Record<ConditionPrepStatus, number>> = {
      to_do: 0,
      waiting: 1,
      ready: 2,
      with_underwriter: 3,
    };
    const from = rank[condition.prep_status];
    const target = rank[to];
    if (from !== undefined && target !== undefined && target < from) {
      setRefusal(null);
      setMoveBack({ condition, to, mode: "move-back" });
      return;
    }
    // LP-956 — A CONDITION HER OWN CANNOT WAIT ON HER: ask who it waits on instead of sending her.
    if (to === "waiting" && waitingOnFor(condition) === null) {
      setRefusal(null);
      setWaitingAsk({ condition, to });
      return;
    }
    prepStatus.mutate(
      {
        conditionId: condition.id,
        to,
        waiting_on: to === "waiting" ? waitingOnFor(condition) : null,
        expected_updated_at: condition.updated_at,
      },
      {
        // THE ROW ROLLS BACK BY ITSELF. The mutation never writes to local state, so a refusal
        // leaves the cache holding the server's row and the select snaps back to it — and the
        // server's SENTENCE is what the processor reads, never a wording of ours (spec §6 rule 5).
        onError: (error) =>
          notifyError({
            title: "That status could not be changed",
            whatToDo: getErrorMessage(error),
          }),
      },
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="outline" size="sm" onClick={onAddByHand}>
          Add a condition
        </Button>
        <Button variant="outline" size="sm" onClick={onPaste}>
          Paste
        </Button>
        <Button size="sm" onClick={onUploadAnother}>
          Upload sheet
        </Button>
      </div>

      <RoundStrip
        rounds={rounds}
        total={allRows.length}
        busyRoundId={attach.isPending ? (attach.variables?.roundId ?? null) : null}
        onOpenDetails={(round) => {
          setEnrichment(null);
          setOpenRoundId(round.id);
        }}
        onAttachPdf={(roundId, file) =>
          attach.mutate(
            { roundId, file },
            {
              onSuccess: (result) => {
                notifySuccess({
                  title: "The lender’s PDF was attached",
                  consequence: "It merged into that round. No new conditions, no second round.",
                });
                setEnrichment(result);
                setOpenRoundId(result.round_id);
              },
              onError: (error) =>
                notifyError({
                  title: "That PDF could not be attached",
                  whatToDo: getErrorMessage(error),
                }),
            },
          )
        }
      />

      {/* ABOVE THE SUMMARY BAR (S2-06's Must-match). It opens by itself after an import that has
          something to say, and closing it is per round — see `hiddenPanelRoundId`. */}
      {comparisonRound !== null && hiddenPanelRoundId !== comparisonRound.id ? (
        <RoundComparisonPanel
          round={comparisonRound}
          previousRoundNumber={previousRoundNumber}
          conditions={allRows}
          rounds={rounds}
          pending={
            confirmCleared.isPending || resolveReworded.isPending || switchCompleteness.isPending
          }
          refusal={panelRefusal}
          onConfirm={(conditionIds) => {
            setPanelRefusal(null);
            confirmCleared.mutate(
              { roundId: comparisonRound.id, condition_ids: conditionIds },
              {
                onSuccess: () =>
                  notifySuccess({
                    title: `${conditionIds.length} recorded as cleared`,
                    consequence: `Each one says it came from round ${comparisonRound.comparison?.round_number} on ${comparisonRound.date_printed ?? comparisonRound.round_date}.`,
                  }),
                // THE SERVER'S SENTENCE, SHOWN IN THE PANEL rather than as a toast that vanishes —
                // the refusal is about the list she is looking at, and she has to act on it.
                onError: (error) => setPanelRefusal(getErrorMessage(error)),
              },
            );
          }}
          onNotNow={() => setHiddenPanelRoundId(comparisonRound.id)}
          onResolveReworded={(oldId, newId, same) => {
            setPanelRefusal(null);
            resolveReworded.mutate(
              { roundId: comparisonRound.id, old_id: oldId, new_id: newId, same },
              {
                onSuccess: () =>
                  notifySuccess({
                    title: same ? "Marked as the same condition" : "Kept as two conditions",
                    consequence: same
                      ? "The old one is Replaced and points at the one that replaced it. Nothing was deleted."
                      : "Both stay exactly as they are.",
                  }),
                onError: (error) => setPanelRefusal(getErrorMessage(error)),
              },
            );
          }}
          onSwitchToFull={() => {
            setPanelRefusal(null);
            switchCompleteness.mutate(
              {
                roundId: comparisonRound.id,
                completeness: "full",
                expected_updated_at: comparisonRound.updated_at,
              },
              {
                onSuccess: () =>
                  notifySuccess({
                    title: "Switched to Full list",
                    consequence:
                      "Conditions missing from this sheet are now suggested as cleared. Nothing is cleared until you confirm.",
                  }),
                onError: (error) => setPanelRefusal(getErrorMessage(error)),
              },
            );
          }}
          onHide={() => setHiddenPanelRoundId(comparisonRound.id)}
        />
      ) : null}

      {/* S3-02 (LP-920): the newest imported round's plan, until she confirms it. */}
      {/* LP-952: the reading's state above its plan — running, failed, or never started. */}
      {newestImported ? <ReadingStatus fileId={fileId} roundId={newestImported.id} /> : null}
      {newestImported ? (
        <RoundPlanPanel
          fileId={fileId}
          round={newestImported}
          conditions={allRows}
          onOpenCondition={setOpenConditionId}
          onConfirmReading={setConfirmReadingId}
        />
      ) : null}

      {/* LP-924: what accepted evidence changes in the file's figures (S3-09), until applied. */}
      <FiguresCheckPanel fileId={fileId} />
      <ConditionPackagePanel fileId={fileId} />

      {/* LP-922: the round's unsent drafts, once the plan panel is gone. */}
      <RoundDrafts fileId={fileId} onOpenDraft={setDraftId} />

      {summary.data ? (
        <ConditionsSummaryBar summary={summary.data} state={urlState} onFilter={applyUrl} />
      ) : (
        <Skeleton className="h-14 w-full" />
      )}

      <ConditionsFilterRow
        state={urlState}
        onChange={applyUrl}
        search={searchInput}
        onSearchChange={setSearchInput}
        roundNumbers={roundNumbers}
      />

      {/* S1-08'S SAFETY LINE SURVIVES STAGE 2. A partial round leaves everything it did not mention
          alone, and absence must not read as removal — still true once the list has status controls,
          and still the sentence that says so. The Stage 1 "no status control of any kind" callout is
          NOT carried over: this screen has them, and repeating it would be false. */}
      {rounds.find((round) => round.status === "imported")?.completeness === "partial" ? (
        <p className="flex items-start gap-2 rounded-md border border-input bg-muted/40 p-2.5 text-xs text-muted-foreground">
          <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          <span>
            The newest round was just some conditions. Conditions that weren’t in it were left as
            they are — nothing is removed or cleared.
          </span>
        </p>
      ) : null}

      {filtered.isPending ? (
        <div className="flex flex-col gap-2" aria-busy>
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
        </div>
      ) : (
        <ConditionsList
          conditions={rows}
          settledFrom={allRows}
          suggestedIds={suggestedIds}
          suggestedRoundNumber={suggestionRound?.comparison?.round_number ?? null}
          state={urlState}
          search={searchInput}
          capped={filtered.data?.capped ?? false}
          selected={selectedIds}
          onSelectedChange={setSelectedIds}
          onOpen={setOpenConditionId}
          onOpenDraft={setDraftId}
          onMovePrepStatus={movePrep}
          onClearFilters={() => {
            setSearchInput("");
            applyUrl({
              ...urlState,
              roundNumber: null,
              lenderStatus: [],
              prepStatus: [],
              owner: [],
              bucketKind: [],
              step: [],
              check: null,
            });
          }}
        />
      )}

      <WithdrawnSection fileId={fileId} />

      <ConditionsBulkBar
        selected={selected}
        pending={bulk.isPending}
        onClear={() => setSelectedIds(new Set())}
        onSetPrepStatus={(to) =>
          runBulk({ condition_ids: selected.map((row) => row.id), action: "prep_status", to })
        }
        onSetOwner={(value: OwnerHint) =>
          runBulk({ condition_ids: selected.map((row) => row.id), action: "owner", owner: value })
        }
        onRecordAnswer={() => {
          setRefusal(null);
          setAnswerFor(selected);
        }}
      />

      <RoundDetailsSheet
        round={openRound}
        enrichment={enrichment}
        open={openRound !== null}
        onOpenChange={(next) => {
          if (!next) {
            setOpenRoundId(null);
            setEnrichment(null);
          }
        }}
      />

      <ConditionDetailSheet
        conditions={rows}
        openId={openConditionId}
        onOpenChange={(next) => {
          if (!next) setOpenConditionId(null);
        }}
        onSelect={setOpenConditionId}
        onMovePrepStatus={movePrep}
        onSetOwner={(condition, value) =>
          owner.mutate(
            { conditionId: condition.id, owner: value, expected_updated_at: condition.updated_at },
            {
              onError: (error) =>
                notifyError({
                  title: "The owner could not be changed",
                  whatToDo: getErrorMessage(error),
                }),
            },
          )
        }
        onRecordAnswer={(condition) => {
          setRefusal(null);
          setAnswerFor([condition]);
        }}
        onReopen={(condition) => {
          setRefusal(null);
          setMoveBack({ condition, to: null, mode: "reopen" });
        }}
        suggestedIds={suggestedIds}
        suggestedRoundNumber={suggestionRound?.comparison?.round_number ?? null}
        // ONE CONDITION THROUGH THE SAME DOOR THE PANEL USES — "the suggestion is per condition, so
        // she can also confirm one from the detail sheet" (spec §LP-915). It is the round's endpoint
        // either way, because the round's saved comparison is what authorises the verdict at all.
        //
        // UNDEFINED WHEN NO ROUND HAS BEEN COMPARED, so the sheet renders no block rather than a
        // button with nowhere to send the click.
        onConfirmSuggestion={
          suggestionRound === null
            ? undefined
            : (condition) =>
                confirmCleared.mutate(
                  // `resolve_rest: false` — ONE condition answered here; the round's other
                  // questions stay pending until she decides them (LP-915 review).
                  {
                    roundId: suggestionRound.id,
                    condition_ids: [condition.id],
                    resolve_rest: false,
                  },
                  {
                    onSuccess: () =>
                      notifySuccess({
                        title: `${condition.lender_code ?? "That condition"} recorded as cleared`,
                        consequence: `It says it came from round ${suggestionRound.comparison?.round_number}. The round's other suggestions are still waiting.`,
                      }),
                    onError: (error) =>
                      notifyError({
                        title: "That could not be recorded",
                        whatToDo: getErrorMessage(error),
                      }),
                  },
                )
        }
        onConfirmReading={(condition) => setConfirmReadingId(condition.id)}
        onOpenDraft={setDraftId}
        fileId={fileId}
        onAddItem={(condition, name, performer) =>
          addItem.mutate({ conditionId: condition.id, name, performers: [performer] })
        }
        onSetNextStep={(condition, option) =>
          setNextStep.mutate(
            { conditionId: condition.id, next_step: option },
            {
              onError: (error) =>
                notifyError({
                  title: "The step was not changed",
                  whatToDo: getErrorMessage(error),
                }),
            },
          )
        }
        onMarkItemDone={(condition, item, done) =>
          updateItem.mutate(
            { conditionId: condition.id, itemId: item.id, status: done ? "done" : "open" },
            {
              onError: (error) =>
                notifyError({ title: "That was not recorded", whatToDo: getErrorMessage(error) }),
            },
          )
        }
      />
      <ConditionDraftDialog fileId={fileId} draftId={draftId} onClose={() => setDraftId(null)} />
      <ConfirmReadingFor
        fileId={fileId}
        conditions={rows}
        conditionId={confirmReadingId}
        onClose={() => setConfirmReadingId(null)}
      />

      <RecordAnswerDialog
        conditions={answerFor ?? []}
        open={answerFor !== null && answerFor.length > 0}
        onOpenChange={(next) => {
          if (!next) setAnswerFor(null);
        }}
        refusal={refusal}
        pending={verdict.isPending || bulk.isPending}
        onSubmit={(values) => {
          const targets = answerFor ?? [];
          if (targets.length === 0) return;
          setRefusal(null);
          // ONE ROW GOES THROUGH THE SINGLE WRITE, MANY THROUGH BULK — and both reach the same
          // service, so a rule enforced on one is enforced on eleven.
          if (targets.length === 1 && targets[0]) {
            const only = targets[0];
            verdict.mutate(
              { conditionId: only.id, ...values, expected_updated_at: only.updated_at },
              {
                onSuccess: () => setAnswerFor(null),
                onError: (error) => setRefusal(getErrorMessage(error)),
              },
            );
            return;
          }
          runBulk(
            {
              condition_ids: targets.map((row) => row.id),
              action: "verdict",
              status: values.status,
              source_kind: values.source_kind,
              source_date: values.source_date,
              note: values.note,
            },
            () => setAnswerFor(null),
          );
        }}
      />

      <MoveBackDialog
        condition={moveBack?.condition ?? null}
        to={moveBack?.to ?? null}
        mode={moveBack?.mode ?? "move-back"}
        open={moveBack !== null}
        onOpenChange={(next) => {
          if (!next) setMoveBack(null);
        }}
        refusal={refusal}
        pending={prepStatus.isPending || reopen.isPending}
        onSubmit={(reason) => {
          if (!moveBack) return;
          setRefusal(null);
          const { condition, to, mode } = moveBack;
          const settle = {
            onSuccess: () => setMoveBack(null),
            onError: (error: unknown) => setRefusal(getErrorMessage(error)),
          };
          if (mode === "reopen") {
            reopen.mutate(
              { conditionId: condition.id, reason, expected_updated_at: condition.updated_at },
              settle,
            );
          } else if (to === "waiting" && waitingOnFor(condition) === null) {
            // LP-956 — moving back to Waiting on her own task: ask who, carrying her reason along.
            setMoveBack(null);
            setWaitingAsk({ condition, to, reason });
          } else if (to) {
            prepStatus.mutate(
              {
                conditionId: condition.id,
                to,
                reason,
                waiting_on: to === "waiting" ? waitingOnFor(condition) : null,
                expected_updated_at: condition.updated_at,
              },
              settle,
            );
          }
        }}
      />

      <WaitingOnDialog
        condition={waitingAsk?.condition ?? null}
        open={waitingAsk !== null}
        onOpenChange={(next) => {
          if (!next) setWaitingAsk(null);
        }}
        refusal={refusal}
        pending={prepStatus.isPending}
        onChoose={(owner) => {
          if (!waitingAsk) return;
          setRefusal(null);
          const { condition, to, reason } = waitingAsk;
          prepStatus.mutate(
            {
              conditionId: condition.id,
              to,
              reason,
              waiting_on: owner,
              expected_updated_at: condition.updated_at,
            },
            {
              onSuccess: () => setWaitingAsk(null),
              onError: (error: unknown) => setRefusal(getErrorMessage(error)),
            },
          );
        }}
      />
    </div>
  );

  /**
   * Run a bulk write and REPORT WHAT IT ACTUALLY DID.
   *
   * 200 WITH REFUSALS AS DATA, so `onSuccess` runs for a partly-applied write. A dialog that closed
   * on success without reading `refused` would tell a processor eleven rows were cleared when one was
   * skipped — which is why the toast carries `bulkResultSummary` rather than a count of what was sent.
   */
  function runBulk(input: Parameters<typeof bulk.mutate>[0], onDone?: () => void) {
    bulk.mutate(input, {
      onSuccess: (result) => {
        onDone?.();
        setSelectedIds(new Set());
        notifySuccess({
          title: bulkResultSummary(result),
          consequence:
            result.refused.length > 0
              ? "The skipped ones were left exactly as they were."
              : "Every selected condition was updated.",
        });
      },
      onError: (error) =>
        notifyError({ title: "Nothing was changed", whatToDo: getErrorMessage(error) }),
    });
  }
}
