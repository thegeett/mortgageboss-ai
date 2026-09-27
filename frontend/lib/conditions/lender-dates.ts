import type { ConditionRound } from "@/lib/types/conditions";

/**
 * The dates the lender printed, read off the newest round that carries any (LP-917-lite, S2-11).
 *
 * PURE, AND `today` IS A PARAMETER FOR A REASON. The rail draws "Close by and income docs · 38 days",
 * a countdown, so a test against the real clock would pass on the day it was written and fail the next
 * morning. S2-11 itself was drawn with today = 09/26/2026 and a close-by of 11/03/2026; the same
 * fixture is 37 days on 09/27. The number is arithmetic, and the arithmetic is what is pinned.
 *
 * NOTHING HERE IS GUESSED AND NOTHING IS COLOURED. Spec: "Plain display only. No colours for 'soon',
 * no alerts." A date the lender did not print is absent, never inferred from another one — and a file
 * with no dated round says so rather than rendering four dashes, which would read as a letter we failed
 * to parse (the same distinction `LetterDetails` draws between a paste and an unreadable letterhead).
 *
 * THE FACT KEYS ARE THE LENDER'S OWN PRINTED LABELS, character for character, exactly as
 * `review-side-panel.tsx` states: `_split_loan_facts` stores whatever label it matched from its closed
 * set, so "Rate Lock Exp" is the lender's spelling and not ours to tidy.
 */

/** The lender's printed label for each date the rail shows. */
const MUST_NOT_CLOSE_BEFORE = "Must Not Close Before";
const MUST_FUND_BY = "Must Fund By";
const RATE_LOCK_EXP = "Rate Lock Exp";

/** One round's three printed dates, for a caller holding a single round rather than a file's list. */
export interface LenderFacts {
  mustNotCloseBefore: string | null;
  mustFundBy: string | null;
  rateLockExpires: string | null;
}

/**
 * The three dates off ONE round — the round card's "Lock 09/30/2026 · Not before 09/30/2026".
 *
 * SEPARATE FROM `lenderDates` BECAUSE THE QUESTION IS DIFFERENT. The rail asks "what are this FILE's
 * lender dates", which means choosing a round; a round card already knows which round it is drawing and
 * must show that round's own letter, not the file's newest. Sharing the key constants is the point: the
 * lender's printed labels are declared once in this module and nowhere else.
 *
 * AN EMPTY STRING IS ABSENT. The reader stores `"Rate Lock Exp": ""` when the lender printed the row
 * and left it blank, and `""` would render as a value that is there but invisible.
 */
export function lenderFactsFor(round: ConditionRound): LenderFacts {
  const facts = (round.header?.loan_facts as Record<string, string> | undefined) ?? {};
  const read = (key: string): string | null => {
    const value = facts[key];
    return value !== undefined && value.trim() !== "" ? value : null;
  };
  return {
    mustNotCloseBefore: read(MUST_NOT_CLOSE_BEFORE),
    mustFundBy: read(MUST_FUND_BY),
    rateLockExpires: read(RATE_LOCK_EXP),
  };
}

export interface SoonestExpiry {
  /** ISO, as `expiry_dates` stores it. */
  date: string;
  /**
   * Which of the lender's twelve rows fall on that date, in the lender's table order.
   *
   * A LIST BECAUSE A TIE IS THE ORDINARY CASE. S2-11's own fixture has close-by and income docs both
   * on 11/03/2026, and it names both ("Close by and income docs"). Picking one would silently drop
   * half of what expires that day.
   */
  labels: string[];
  /** Whole days from `today`. Negative when the date has passed; 0 on the day itself. */
  days: number;
}

export interface LenderDates {
  /** The round these came from — the section's "From round 2, printed 09/10". */
  roundNumber: number | null;
  /** ISO, or null when the round carries no printed date (its `round_date` is not the lender's). */
  datePrinted: string | null;
  /** As the lender printed them, so they are shown as strings rather than re-formatted dates. */
  mustNotCloseBefore: string | null;
  mustFundBy: string | null;
  rateLockExpires: string | null;
  soonestExpiry: SoonestExpiry | null;
}

/**
 * The newest imported round that actually carries lender dates, or null.
 *
 * "FULL, OR PARTIAL WITH ITS PDF ATTACHED" IS EXPRESSED AS "HAS A HEADER OR AN EXPIRY TABLE", which is
 * the same set read off the data instead of off two flags. A paste has neither until its PDF is
 * attached, and attaching one is precisely what gives a partial round its letter — so asking what the
 * round HOLDS needs no separate completeness test, and cannot disagree with one.
 *
 * NEWEST BY ROUND NUMBER, NOT BY `created_at`. The Done-when is "all taken from round 2 and not round
 * 1", and a round imported out of creation order would otherwise win on a timestamp.
 */
export function roundWithLenderDates(rounds: ConditionRound[]): ConditionRound | null {
  const candidates = rounds.filter(
    (round) =>
      round.status === "imported" &&
      round.round_number !== null &&
      (round.header !== null || hasAnyExpiry(round)),
  );
  if (candidates.length === 0) return null;
  return candidates.reduce((newest, round) =>
    (round.round_number as number) > (newest.round_number as number) ? round : newest,
  );
}

function hasAnyExpiry(round: ConditionRound): boolean {
  return Object.values(round.expiry_dates ?? {}).some((value) => Boolean(value));
}

/**
 * Whole days from `today` to an ISO date, both read as calendar days.
 *
 * COMPARED AT UTC MIDNIGHT so the answer is a number of dates rather than a number of 24-hour spans.
 * Built from `Date.UTC` on the parsed parts instead of `new Date("2026-11-03")` arithmetic, because a
 * local-midnight reading shifts the difference by one for any viewer east or west of UTC — a countdown
 * that reads 37 in London and 38 in Denver is the kind of defect nothing here would catch.
 */
export function daysUntil(iso: string, today: string): number | null {
  const target = utcDay(iso);
  const from = utcDay(today);
  if (target === null || from === null) return null;
  return Math.round((target - from) / 86_400_000);
}

function utcDay(iso: string): number | null {
  const [year, month, day] = iso.split("-").map(Number);
  if (!year || !month || !day) return null;
  if (!Number.isFinite(year) || !Number.isFinite(month) || !Number.isFinite(day)) return null;
  return Date.UTC(year, month - 1, day);
}

/**
 * The soonest document expiry on a round's table, and everything expiring with it.
 *
 * `expiryLabels` IS THE CALLER'S so this module holds no second copy of the lender's twelve keys —
 * `review-side-panel.tsx` owns that vocabulary and has since S1-04, and two copies would diverge the
 * first time the lender's table changed.
 *
 * PAST DATES STILL COUNT. An expiry that has already gone by is the most important one on the table,
 * and skipping it would make a lapsed document invisible exactly when it matters. The day count goes
 * negative and the caller renders it plainly (no colour — spec).
 */
export function soonestExpiry(
  round: ConditionRound,
  expiryLabels: readonly (readonly [key: string, label: string])[],
  today: string,
): SoonestExpiry | null {
  const dates = round.expiry_dates ?? {};
  let soonest: string | null = null;
  for (const [key] of expiryLabels) {
    const value = dates[key];
    if (!value) continue;
    if (soonest === null || value < soonest) soonest = value;
  }
  if (soonest === null) return null;

  // In the lender's own table order, so "Close by and income docs" reads as the sheet does.
  const labels = expiryLabels.filter(([key]) => dates[key] === soonest).map(([, label]) => label);
  const days = daysUntil(soonest, today);
  return { date: soonest, labels, days: days ?? 0 };
}

/**
 * Everything the rail's Lender dates section shows, or null when no round has any.
 *
 * NULL RATHER THAN AN OBJECT OF NULLS, so the caller renders "No dates from the lender yet." — the
 * spec's own sentence — instead of four em dashes. The two say different things: one is "the lender has
 * not given us dates", the other is "this round's letter had these fields empty".
 */
export function lenderDates(
  rounds: ConditionRound[],
  expiryLabels: readonly (readonly [key: string, label: string])[],
  today: string,
): LenderDates | null {
  const round = roundWithLenderDates(rounds);
  if (round === null) return null;

  // THROUGH `lenderFactsFor`, so the file's rail and a single round's card read one implementation.
  return {
    roundNumber: round.round_number,
    datePrinted: round.date_printed,
    ...lenderFactsFor(round),
    soonestExpiry: soonestExpiry(round, expiryLabels, today),
  };
}

/**
 * "Close by and income docs · 38 days" — the line under the soonest expiry.
 *
 * LOWER-CASED AFTER THE FIRST, because the design reads "Close by and income docs" rather than "Close
 * by and Income docs": the labels are sentence-case row headings, and joined into a phrase only the
 * first keeps its capital.
 *
 * "docs" IS SINGULAR-AGNOSTIC AND THE DAY COUNT IS NOT. "1 days" is the sort of thing that survives
 * review for months, so the noun is agreed with the number.
 */
export function expiryLine(expiry: SoonestExpiry): string {
  const [first, ...rest] = expiry.labels;
  const names = [first, ...rest.map((label) => label.toLowerCase())].filter(Boolean);
  const subject =
    names.length === 0
      ? "Documents"
      : names.length === 1
        ? `${names[0]} docs`
        : `${names.slice(0, -1).join(", ")} and ${names.at(-1)} docs`;
  const magnitude = Math.abs(expiry.days);
  const noun = magnitude === 1 ? "day" : "days";
  // A DATE ALREADY PAST SAYS SO IN WORDS, not as a minus sign a reader has to interpret.
  const when = expiry.days < 0 ? `${magnitude} ${noun} ago` : `${magnitude} ${noun}`;
  return `${subject} · ${when}`;
}
