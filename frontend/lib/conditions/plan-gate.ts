import type { ReadingState, RoundPlan } from "@/lib/types/conditions";

/**
 * LP-964 — which step of a newly imported round the conditions page is on.
 *
 * The page used to render everything at once after Import: the list, then a "Reading…" line above
 * it, then the plan landing on top of the list a moment later. That showed the same conditions twice,
 * once as proposals in the plan and once in the list with those proposals already in its Next step
 * column, and the page jumped as each part arrived (the owner, 2026-10-06). Now one step shows at a
 * time:
 *
 * - `loading` — the round's reading or plan has not answered yet. A placeholder, not the list, so the
 *   list never flashes up and then vanishes.
 * - `reading` — the AI is reading the round, or the reading failed or never started and nothing is
 *   planned yet. The reading card, not the list.
 * - `plan` — a plan is waiting for her to confirm. The plan, not the list.
 * - `list` — the normal page: no imported round, the plan is confirmed, or there is nothing to plan.
 *
 * In `loading`, `reading` and `plan` the list is COLLAPSED, NEVER REMOVED: the page shows one line with
 * a "Show them now" link (see `ConditionsListView`). That is the escape hatch for a stuck reading and
 * for checking a condition's full wording.
 *
 * IT FAILS OPEN. A plan or reading request that errored is not pending and has no data, so it lands
 * on `list`. A broken endpoint must not hide the conditions.
 */
export type PlanGatePhase = "loading" | "reading" | "plan" | "list";

export function planGatePhase({
  hasImportedRound,
  reading,
  readingPending,
  plan,
  planPending,
}: {
  hasImportedRound: boolean;
  reading: ReadingState | undefined;
  /** The query's own `isPending`. Only `true` means loading; `undefined` is not loading. */
  readingPending: boolean | undefined;
  plan: RoundPlan | undefined;
  planPending: boolean | undefined;
}): PlanGatePhase {
  if (!hasImportedRound) return "list";
  // A confirmed plan settles it, whatever the reading says.
  if (plan?.confirmed_at) return "list";
  if (readingPending === true || planPending === true) return "loading";

  const running = reading?.state === "queued" || reading?.state === "reading";
  if (running) return "reading";
  if (plan && plan.planned > 0) return "plan";
  // Nothing planned. If conditions are still unread (failed, or never started), the reading card is
  // the thing to act on, since it carries Read again. Otherwise there is nothing to plan.
  if (reading && reading.state !== "done" && reading.unread > 0) return "reading";
  return "list";
}
