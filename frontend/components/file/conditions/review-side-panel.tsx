"use client";

import { Button } from "@/components/ui/button";
import type { ConditionRound } from "@/lib/types/conditions";
import { Copy } from "lucide-react";

/**
 * The lender team's roles, in the order the letter prints them (`_TEAM_LABELS` in `readers/uwm.py`).
 *
 * ⚠️ THE READER RETURNS A LIST, NOT A MAP, AND THAT IS LOAD-BEARING. `_split_header` appends
 * `{role, name, phone_ext}` in printed order and deliberately keeps a role whose value is EMPTY:
 * "`Closer:` with nothing after it is the lender asserting the role exists and is unfilled".
 * Rendering from the list rather than from a fixed key list preserves both facts — the order the
 * lender chose, and the difference between "no closer assigned yet" and "this letter has no closer
 * field at all", which its comment says the UI cannot recover afterwards.
 */
interface TeamMember {
  role: string;
  name: string;
  phone_ext: string | null;
}

/**
 * The seven figures S1-04 shows, keyed by the lender's OWN printed label.
 *
 * ⚠️ NOT SNAKE_CASE, AND NOT OURS. `_split_loan_facts` stores whatever label it matched from its
 * closed set — "Note Rate", "Housing / Debt Ratios" — so these strings are the lender's vocabulary
 * and must match character for character. The display label beside each is the design's wording.
 */
const FIGURES: [key: string, label: string][] = [
  ["Note Rate", "Note rate"],
  ["Housing / Debt Ratios", "Housing / debt ratios"],
  ["Verified Income", "Verified income"],
  ["Verified Assets", "Verified assets"],
  ["Max Funds to Close", "Max funds to close"],
  ["Must Not Close Before", "Must not close before"],
  ["Rate Lock Exp", "Rate lock exp."],
];

/**
 * The twelve expiry rows, in the lender's own table order (`_EXPIRY_KEYS` in `readers/uwm.py`).
 *
 * ⚠️ ALL TWELVE ALWAYS, INCLUDING THE EMPTY ONES. S1-04 requires "all 12 keys in the lender's order,
 * '—' where empty" — because a missing row and an empty row mean different things on a lender's
 * table, and collapsing the absent ones would quietly redraw the lender's own document.
 *
 * The keys are the server's; the labels are the design's sentence case ("Close by", not the
 * reader's printed "Close By").
 */
const EXPIRY: [key: string, label: string][] = [
  ["close_by", "Close by"],
  ["appraisal", "Appraisal"],
  ["asset", "Asset"],
  ["cpl", "CPL"],
  ["credit", "Credit"],
  ["income", "Income"],
  ["insurance", "Insurance"],
  ["other", "Other"],
  ["payoff", "Payoff"],
  ["short_sale", "Short sale"],
  ["title", "Title"],
  ["vob", "VOB"],
];

/** `2026-10-30` → `10/30/2026`. Anything unparseable is shown as it arrived rather than blanked. */
function usDate(value: string | null | undefined): string {
  if (!value) return "—";
  const [year, month, day] = value.split("-");
  return year && month && day ? `${month}/${day}/${year}` : value;
}

function Row({ label, value }: { label: string; value: string | null }) {
  const empty = !value || value === "—";
  return (
    <div className="flex items-baseline justify-between gap-3 py-0.5">
      <dt className="shrink-0 text-xs text-muted-foreground">{label}</dt>
      <dd
        className={
          empty
            ? "text-right text-xs text-muted-foreground"
            : "text-right text-xs text-foreground-2"
        }
      >
        {empty ? "—" : value}
      </dd>
    </div>
  );
}

function Block({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mt-3 first:mt-0">
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{title}</p>
      <dl className="mt-1">{children}</dl>
    </div>
  );
}

/**
 * "Also read from the letter" — the side panel of the review screen (S1-04).
 *
 * ⚠️ A PASTE HAS NO LETTER, AND SAYS SO RATHER THAN SHOWING EMPTY FIELDS (S1-07). `header` is null
 * for a pasted round, and eleven rows of "—" would read as a letter we failed to parse instead of a
 * source that never had one.
 *
 * ⚠️ THE MORTGAGEE CLAUSE IS MISSING FROM THE SERVER, NOT FROM HERE. S1-04 shows the clause with a
 * Copy button, and `condition_round.py`'s own comment describes `header` as
 * `{loan_facts, lender_team, dates, mortgagee_clause?}` — but `_split_header` returns only
 * `{lender_team, broker_contact}`, the reader stores the clause on the SHEET
 * (`sheet.mortgagee_clause`), and the parse task never folds it in. So the key that comment promises
 * is one nothing writes.
 *
 * Rendered conditionally rather than stubbed: when the backend starts sending it this block appears
 * with no change here, and until then nobody mistakes a missing section for a rendering bug.
 * Recorded against LP-909 rather than worked around.
 */
export function ReviewSidePanel({ round }: { round: ConditionRound }) {
  const header = round.header ?? null;
  const team = (header?.lender_team as TeamMember[] | undefined) ?? [];
  const facts = (header?.loan_facts as Record<string, string> | undefined) ?? {};
  const clause = header?.mortgagee_clause as string | undefined;
  const expiry = round.expiry_dates ?? {};

  return (
    <aside className="flex flex-col gap-1 rounded-lg border border-input bg-card p-3.5">
      <p className="text-sm font-semibold text-foreground">Also read from the letter</p>

      {header === null ? (
        <p className="mt-2 max-w-prose text-xs text-muted-foreground">
          A paste has no letter, so there are no lender details to read. Attaching the lender’s PDF
          after import fills this in — it merges into this round and creates no second one.
        </p>
      ) : (
        <>
          <Block title="Lender team">
            {team.length === 0 ? (
              <Row label="Not found on this sheet." value={null} />
            ) : (
              team.map((member) => (
                <Row
                  key={member.role}
                  label={member.role}
                  value={
                    member.name
                      ? member.phone_ext
                        ? `${member.name} ext. ${member.phone_ext}`
                        : member.name
                      : null
                  }
                />
              ))
            )}
          </Block>

          <Block title="Loan figures on the letter">
            {Object.keys(facts).length === 0 ? (
              <Row label="Not found on this sheet." value={null} />
            ) : (
              FIGURES.map(([key, label]) => (
                <Row key={key} label={label} value={facts[key] ?? null} />
              ))
            )}
          </Block>
        </>
      )}

      {/* The expiry table is on its own column, so it survives a header the reader could not find —
          which is exactly S1-11: "the side panel says 'Not found on this sheet.' for the team and
          the figures, but still shows the expiry dates". */}
      <Block title="Document expiry (lender’s table)">
        {EXPIRY.map(([key, label]) => (
          <Row key={key} label={label} value={usDate(expiry[key])} />
        ))}
      </Block>

      {clause ? (
        <Block title="Mortgagee clause">
          <div className="flex items-start gap-2">
            <p className="min-w-0 flex-1 text-xs text-foreground-2">{clause}</p>
            <Button
              variant="outline"
              size="sm"
              className="h-7 w-7 shrink-0 p-0"
              title="Copy the mortgagee clause"
              onClick={() => void navigator.clipboard?.writeText(clause)}
            >
              <Copy className="h-3 w-3" aria-hidden />
              <span className="sr-only">Copy the mortgagee clause</span>
            </Button>
          </div>
        </Block>
      ) : null}
    </aside>
  );
}
