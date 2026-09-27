"use client";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import type { ConditionGroupBy, ConditionListUrlState } from "@/lib/conditions/list-url";
import { OWNER_LABEL } from "@/lib/conditions/owners";
import { CONDITION_LENDER_STATUS, CONDITION_PREP_STATUS } from "@/lib/status";
import type {
  BucketKind,
  ConditionLenderStatus,
  ConditionPrepStatus,
  OwnerHint,
} from "@/lib/types/conditions";
import { BUCKET_KIND_CHIP } from "@/lib/types/conditions";
import { cn } from "@/lib/utils";
import { ChevronDown, Search } from "lucide-react";

/**
 * The filter row above the list (S2-01): search, then Our status · Lender · Owner · Heading · Round,
 * with Group by on the right.
 *
 * EVERY FILTER HERE IS IN THE URL EXCEPT THE SEARCH, AND THAT ASYMMETRY IS THE POINT. The spec says
 * filters live in the URL "like the pipeline's saved views" so a refresh or a shared link keeps them —
 * but `q` searches `verbatim_text`, the lender's words about a borrower's file. A shared link carrying
 * it would put the wording, or an employer's name, into whatever the recipient pastes it into
 * (ADR-405 as amended). So the search term is component state, held by the caller, and
 * `lib/conditions/list-url.ts` has no field that could serialise it.
 *
 * THE OPTIONS COME FROM THE VOCABULARIES THE ROWS USE. `CONDITION_PREP_STATUS`,
 * `CONDITION_LENDER_STATUS`, `OWNER_LABEL` and `BUCKET_KIND_CHIP` are each already exhaustive over
 * their union, so a member added to the backend appears here the moment the mirror lands — rather
 * than a hand-written option list that silently offers one fewer filter than the data has states.
 */

/** `review` and `pending_review` are in the database by A4 and offered by no control (LP-912). */
const OFFERED_PREP: ConditionPrepStatus[] = ["to_do", "waiting", "ready", "with_underwriter"];
const OFFERED_LENDER: ConditionLenderStatus[] = [
  "open",
  "not_cleared",
  "cleared",
  "waived",
  "superseded",
];
const OFFERED_OWNERS: OwnerHint[] = [
  "borrower",
  "title",
  "insurance",
  "lender",
  "broker",
  "processor",
  "unknown",
];
const OFFERED_KINDS: BucketKind[] = [
  "prior_to_approval",
  "prior_to_docs",
  "prior_to_closing",
  "prior_to_funding",
  "lender_to_clear",
  "master",
  "trailing",
  "unknown",
];

const GROUP_LABEL: Record<ConditionGroupBy, string> = {
  heading: "Lender’s heading",
  owner: "Waiting on",
  prep_status: "Our status",
};

/** One multi-select filter button. Its label carries the count, so an applied filter is visible. */
function FilterMenu<T extends string>({
  label,
  options,
  selected,
  labelFor,
  onToggle,
}: {
  label: string;
  options: readonly T[];
  selected: readonly T[];
  labelFor: (value: T) => string;
  onToggle: (next: T[]) => void;
}) {
  const active = selected.length > 0;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          // ACTIVE FILTERS ARE HIGHLIGHTED IN THE ROW (S2-09 Must-match: "the active filters are
          // highlighted … and Clear filters appears"). Without it, a processor who navigated back to
          // a filtered link sees an empty list and no indication of why.
          className={cn(active && "border-primary/55 bg-primary/5 text-primary")}
        >
          {label}
          {active ? ` · ${selected.length}` : ""}
          <ChevronDown className="h-3 w-3" aria-hidden />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-56">
        {options.map((option) => (
          <DropdownMenuCheckboxItem
            key={option}
            checked={selected.includes(option)}
            onCheckedChange={(checked) =>
              onToggle(
                checked ? [...selected, option] : selected.filter((value) => value !== option),
              )
            }
          >
            {labelFor(option)}
          </DropdownMenuCheckboxItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function ConditionsFilterRow({
  state,
  onChange,
  search,
  onSearchChange,
  roundNumbers,
}: {
  state: ConditionListUrlState;
  onChange: (next: ConditionListUrlState) => void;
  /** Held by the caller in COMPONENT state — never serialised. See the module docstring. */
  search: string;
  onSearchChange: (next: string) => void;
  /** The imported rounds on this file, newest first, for the Round filter. */
  roundNumbers: number[];
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="relative w-56">
        <Search
          className="pointer-events-none absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2 text-muted-foreground"
          aria-hidden
        />
        <Input
          type="search"
          aria-label="Search code or words"
          placeholder="Search code or words"
          className="pl-7"
          value={search}
          onChange={(event) => onSearchChange(event.target.value)}
        />
      </div>

      <FilterMenu
        label="Our status"
        options={OFFERED_PREP}
        selected={state.prepStatus}
        labelFor={(value) => CONDITION_PREP_STATUS[value].label}
        onToggle={(prepStatus) => onChange({ ...state, prepStatus })}
      />
      <FilterMenu
        label="Lender"
        options={OFFERED_LENDER}
        selected={state.lenderStatus}
        labelFor={(value) => CONDITION_LENDER_STATUS[value].label}
        onToggle={(lenderStatus) => onChange({ ...state, lenderStatus })}
      />
      <FilterMenu
        label="Owner"
        options={OFFERED_OWNERS}
        selected={state.owner}
        labelFor={(value) => OWNER_LABEL[value]}
        onToggle={(owner) => onChange({ ...state, owner })}
      />
      <FilterMenu
        label="Heading"
        options={OFFERED_KINDS}
        selected={state.bucketKind}
        labelFor={(value) => BUCKET_KIND_CHIP[value]}
        onToggle={(bucketKind) => onChange({ ...state, bucketKind })}
      />

      {/* ROUND IS SINGLE-SELECT, unlike its neighbours: "on the sheet of round 2" is one question and
          the endpoint takes one `round`. A multi-select would offer a combination it cannot answer. */}
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant="outline"
            size="sm"
            className={cn(
              state.roundNumber !== null && "border-primary/55 bg-primary/5 text-primary",
            )}
          >
            {state.roundNumber === null ? "Round" : `Round ${state.roundNumber}`}
            <ChevronDown className="h-3 w-3" aria-hidden />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-44">
          <DropdownMenuRadioGroup
            value={state.roundNumber === null ? "" : String(state.roundNumber)}
            onValueChange={(value) =>
              onChange({ ...state, roundNumber: value === "" ? null : Number(value) })
            }
          >
            <DropdownMenuRadioItem value="">Any round</DropdownMenuRadioItem>
            {roundNumbers.map((number) => (
              <DropdownMenuRadioItem key={number} value={String(number)}>
                Round {number}
              </DropdownMenuRadioItem>
            ))}
          </DropdownMenuRadioGroup>
        </DropdownMenuContent>
      </DropdownMenu>

      <span className="flex-1" />

      <span className="text-xs text-muted-foreground">Group by</span>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="outline" size="sm">
            {GROUP_LABEL[state.groupBy]}
            <ChevronDown className="h-3 w-3" aria-hidden />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-48">
          {/* GROUPING IS NOT A FILTER and is not highlighted like one: regrouping hides nothing, so
              treating it as an active filter would point "Clear filters" at the wrong control. */}
          <DropdownMenuLabel>Group by</DropdownMenuLabel>
          <DropdownMenuSeparator />
          <DropdownMenuRadioGroup
            value={state.groupBy}
            onValueChange={(value) => onChange({ ...state, groupBy: value as ConditionGroupBy })}
          >
            {(Object.keys(GROUP_LABEL) as ConditionGroupBy[]).map((value) => (
              <DropdownMenuRadioItem key={value} value={value}>
                {GROUP_LABEL[value]}
              </DropdownMenuRadioItem>
            ))}
          </DropdownMenuRadioGroup>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}
