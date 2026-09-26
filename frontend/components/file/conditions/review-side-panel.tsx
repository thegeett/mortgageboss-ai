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
 * ⚠️ THE MORTGAGEE CLAUSE IS SENT, AND THIS COMMENT USED TO SAY IT WAS NOT. It described the gap
 * accurately — the reader stored the clause on the SHEET and neither writer folded it into `header`
 * — and then the very commit carrying this file CLOSED that gap: `header_with_clause` folds it in at
 * `tasks/conditions.py` and `condition_enrich.py`, both call sites, fill-never-replace intact. So
 * the sentence was false the moment it landed rather than drifting into falsehood later, and a
 * reader trusting it would conclude the Copy button below is dead code and delete it. Caught in
 * review; the fifth instance of this shape in the stage.
 *
 * ⚠️ THE BLOCK IS STILL CONDITIONAL, FOR A DIFFERENT AND PERMANENT REASON. Not "until the backend
 * starts sending it" — it does — but because a PASTED round genuinely has no clause until its PDF is
 * attached. `header?.mortgagee_clause` absent means this round has no letter to take one from, which
 * is a true statement about the round rather than a gap in the pipeline.
 */
export function ReviewSidePanel({ round }: { round: ConditionRound }) {
  return (
    <aside className="flex flex-col gap-1 rounded-lg border border-input bg-card p-3.5">
      <p className="text-sm font-semibold text-foreground">Also read from the letter</p>
      <LetterDetails round={round} />
    </aside>
  );
}

/**
 * The letter's details themselves, without a container.
 *
 * ⚠️ EXTRACTED SO S1-09 RENDERS THE SAME BLOCKS RATHER THAN A SECOND COPY OF THEM. The round-details
 * sheet shows the identical lender team, loan figures, expiry table and mortgagee clause — and
 * writing them again there is precisely the duplication this ticket has been corrected for twice
 * already (a second `refuseSheet`, a second broker handler). Two copies of the twelve expiry keys
 * would diverge the first time the lender's table changed.
 *
 * The container stays with each caller because they differ: the review screen frames this as an
 * `aside` card beside the rows, the details sheet as a section inside a `Sheet`.
 */
export function LetterDetails({ round }: { round: ConditionRound }) {
  const header = round.header ?? null;
  const team = (header?.lender_team as TeamMember[] | undefined) ?? [];
  const facts = (header?.loan_facts as Record<string, string> | undefined) ?? {};
  const clause = header?.mortgagee_clause as string | undefined;
  const expiry = round.expiry_dates ?? {};

  return (
    <>
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
              // ⚠️ KEYED BY POSITION AS WELL AS ROLE. A role is not unique on a real letter — two
              // closers, or two UW IIs, is a thing a lender can print — and a role-only key raised a
              // React duplicate-key error the first time this panel was opened in a browser
              // (LP-909 §5), on a reader bug that emitted `Closer` twice. The reader is fixed; a
              // sheet that genuinely repeats a role must still render both rows.
              team.map((member, index) => (
                <Row
                  key={`${member.role}-${index}`}
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

      {/* ⚠️ SHOWN ONLY WHEN THE LENDER'S TABLE ACTUALLY HELD SOMETHING, AND THE TWO SCREENS THAT
          DISAGREE ARE WHY (LP-909 §5 visual check). S1-11 — a sheet whose header the reader could not
          find — REQUIRES the expiry dates to still show, because they live in their own column and
          survive a missing letterhead. S1-07 — a paste — requires only the "no letter" message and
          the attach hint.
          Both give `header === null`, so the branch above cannot tell them apart. The distinguisher
          is whether any expiry date was read: S1-11's sheet has them, a paste has none. Rendering
          twelve dashes under a sentence that says there is no letter to read them from is the panel
          contradicting itself in the same breath. */}
      {Object.values(expiry).some((value) => value) ? (
        <Block title="Document expiry (lender’s table)">
          {EXPIRY.map(([key, label]) => (
            <Row key={key} label={label} value={usDate(expiry[key])} />
          ))}
        </Block>
      ) : null}

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
    </>
  );
}
