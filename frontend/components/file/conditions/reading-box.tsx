"use client";

import { Button } from "@/components/ui/button";
import { itemWhere } from "@/lib/conditions/next-step";
import {
  OPTION_LABEL,
  PERFORMER_LABEL,
  monthLabel,
  performersLabel,
} from "@/lib/conditions/plan-words";
import type { Condition, ConditionItem, Performer, ReadingItem } from "@/lib/types/conditions";
import {
  Building2,
  Check,
  Link2,
  ListChecks,
  Mail,
  Plus,
  Sparkles,
  TriangleAlert,
  User,
} from "lucide-react";
import { useState } from "react";

/**
 * "How we read it" (S3-01, LP-919): the app's reading of the lender's words, always beside them.
 *
 * AI IS VIOLET AND ALWAYS LABELLED (README rule 2): "Read by AI · 0.93". A reading below the bar says
 * "0.64 · confirm" in the attention tone instead, and offers the confirm dialog (rule 3, S3-03). A
 * reading made without the AI (the library alone) says so, because "Read by AI" would be false.
 *
 * NUMBERS ARE NEVER THE AI'S. Where the reading carries a figure code computed (7086's shortfall), the
 * box says "computed by code" beside it.
 */
export function ReadingBox({
  condition,
  onConfirm,
}: {
  condition: Condition;
  /** Opens S3-03. Offered only when the reading needs her. */
  onConfirm?: () => void;
}) {
  const reading = condition.reading;
  if (!reading) {
    return condition.reading_status === "unread" ? (
      <section className="rounded-lg border border-input bg-card p-3 text-xs text-muted-foreground">
        Not read yet. The panel above the list shows whether the reading is running, and offers to
        read the conditions if it is not.
      </section>
    ) : null;
  }
  const needsHer = condition.reading_status === "needs_confirmation";
  const confidence = condition.reading_confidence;
  const shortfall = reading.figures?.shortfall ?? null;

  return (
    <section className="flex flex-col gap-2 rounded-lg border border-ai/30 bg-ai/5 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-semibold text-foreground">How we read it</p>
        <div className="flex flex-wrap items-center gap-1.5">
          <ReadingChip
            source={reading.source}
            confidence={confidence}
            needsHer={needsHer}
            confirmed={condition.reading_status === "confirmed"}
          />
          {condition.library_type ? (
            <span className="inline-flex items-center gap-1 rounded-md border border-input bg-card px-1.5 py-0.5 text-xs text-foreground-2">
              <ListChecks className="h-3 w-3" aria-hidden />
              Library: {condition.library_type.label}
            </span>
          ) : null}
        </div>
      </div>
      <p className="text-sm leading-relaxed text-foreground">
        {reading.explanation ?? reading.summary}
      </p>
      {shortfall ? (
        <p className="text-xs text-foreground-2">
          Shortfall {money(shortfall.amount)} (required {money(shortfall.required)}, verified{" "}
          {money(shortfall.verified)}) · computed by code
        </p>
      ) : null}
      {condition.library_type ? (
        <p className="text-xs text-muted-foreground">
          Rule: {condition.library_type.rule_label}
          {condition.library_type.rule_note
            ? ` — ${lowerFirst(condition.library_type.rule_note)}`
            : ""}
        </p>
      ) : null}
      {needsHer && onConfirm ? (
        <div className="flex items-center gap-2 border-t border-ai/20 pt-2">
          <TriangleAlert className="h-3.5 w-3.5 text-warning" aria-hidden />
          <p className="flex-1 text-xs text-foreground-2">
            Please confirm how we read this. Nothing is drafted for it until you do.
          </p>
          <Button type="button" size="sm" variant="outline" onClick={onConfirm}>
            Confirm the reading
          </Button>
        </div>
      ) : null}
    </section>
  );
}

function ReadingChip({
  source,
  confidence,
  needsHer,
  confirmed,
}: {
  source: string;
  confidence: number | null;
  needsHer: boolean;
  confirmed: boolean;
}) {
  if (confirmed) {
    return (
      <span className="inline-flex items-center gap-1 rounded-md border border-input bg-card px-1.5 py-0.5 text-xs text-foreground-2">
        Confirmed by you
      </span>
    );
  }
  if (needsHer) {
    return (
      <span
        className="inline-flex items-center gap-1 rounded-md border border-warning/40 bg-warning/10 px-1.5 py-0.5 text-xs text-warning"
        title={confidence === null ? "Read without the AI" : `Confidence ${confidence.toFixed(2)}`}
      >
        <TriangleAlert className="h-3 w-3" aria-hidden />
        {source === "ai" && confidence !== null
          ? `${confidence.toFixed(2)} · confirm`
          : "Library · confirm"}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-md border border-ai/30 bg-ai/10 px-1.5 py-0.5 text-xs text-ai">
      <Sparkles className="h-3 w-3" aria-hidden />
      Read by AI{confidence !== null ? ` · ${confidence.toFixed(2)}` : ""}
    </span>
  );
}

/** The items the reading found (S3-01's "Items · 3"), each with who acts and what is acceptable. */
/** An item as the sheet draws it: the plan's (LP-920) once it exists, the reading's before that. */
type ShownItem = ReadingItem | ConditionItem;

/**
 * The items (S3-01's "Items · 3"), each with who acts, the option, and — for a plan item that shares
 * its need with other conditions — "Same statement as 7086 and 6132 — asked for once" (§4a change 2).
 */
export function ReadingItems({
  items,
  onAdd,
  onMarkDone,
  onOpenDraft,
}: {
  items: ShownItem[];
  /** S3-01's "Add an item" (LP-920). Offered only once the plan exists. */
  onAdd?: (name: string, performer: Performer) => void;
  /** LP-921 — her own task done (or not). Offered on an "I'll do it" item only. */
  onMarkDone?: (item: ConditionItem, done: boolean) => void;
  /** LP-922 — "In borrower email · draft" opens that draft. */
  onOpenDraft?: (draftId: string) => void;
}) {
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [who, setWho] = useState<Performer>("borrower");
  const live = items.filter((item) => !("status" in item) || item.status !== "not_needed");
  // LP-946: a part (one destination of an item several people act on) is shown on its parent's row,
  // "Also: in the borrower email · draft", rather than as a row of its own.
  const partsOf = (id: string) =>
    live.filter(
      (each): each is ConditionItem => "part_of_item_id" in each && each.part_of_item_id === id,
    );
  const shown = live.filter((item) => !("part_of_item_id" in item) || !item.part_of_item_id);
  if (shown.length === 0 && !onAdd) return null;
  return (
    <section className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Items · {shown.length}
        </p>
        {onAdd ? (
          <Button type="button" variant="ghost" size="sm" onClick={() => setAdding(true)}>
            <Plus className="h-3.5 w-3.5" aria-hidden />
            Add an item
          </Button>
        ) : null}
      </div>
      <ol className="flex flex-col gap-2">
        {shown.map((item, index) => (
          <li
            key={`${item.key}-${index}`}
            className="grid grid-cols-[1.5rem_1fr_9rem] gap-3 rounded-lg border border-input bg-card p-3"
          >
            <span className="flex h-5 w-5 items-center justify-center rounded-full border border-input text-xs text-foreground-2">
              {index + 1}
            </span>
            <div className="flex min-w-0 flex-col gap-0.5">
              <p className="text-sm font-semibold text-foreground">{item.name}</p>
              <p className="text-xs text-foreground-2">{itemLine(item)}</p>
              {"shared_with_codes" in item && item.shared_with_codes.length > 0 ? (
                <p className="inline-flex items-center gap-1 text-xs text-primary">
                  <Link2 className="h-3 w-3" aria-hidden />
                  Same statement as {joinCodes(item.shared_with_codes)} — asked for once
                </p>
              ) : null}
              {"waits_on_code" in item && item.waits_on_code ? (
                <p className="text-xs text-muted-foreground">Waits on {item.waits_on_code}</p>
              ) : null}
              {"document_name" in item && item.document_name ? (
                <p className="text-xs text-muted-foreground">
                  Already in the file: {item.document_name}, page {item.document_page ?? 1}
                </p>
              ) : null}
            </div>
            <div className="flex flex-col gap-0.5">
              <p className="inline-flex items-center gap-1 text-sm text-foreground">
                {item.performers[0] === "borrower" || item.performers[0] === "lo" ? (
                  <User className="h-3.5 w-3.5" aria-hidden />
                ) : (
                  <Building2 className="h-3.5 w-3.5" aria-hidden />
                )}
                {performersLabel(item.performers)}
              </p>
              <p className="text-xs text-muted-foreground">{OPTION_LABEL[item.option]}</p>
              {"id" in item ? (
                <ItemWhere item={item} onMarkDone={onMarkDone} onOpenDraft={onOpenDraft} />
              ) : null}
              {"id" in item
                ? partsOf(item.id).map((part) => (
                    <p key={part.id} className="text-xs text-foreground-2">
                      Also: {performersLabel(part.performers)} —{" "}
                      {itemWhere(part) ?? (part.option === "i_will_do_it" ? "your task" : "")}
                    </p>
                  ))
                : null}
            </div>
          </li>
        ))}
      </ol>
      {adding && onAdd ? (
        <div className="flex items-center gap-2 rounded-lg border border-input bg-card p-2">
          <input
            aria-label="New item"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="What else the lender asks for"
            className="h-8 flex-1 rounded-md border border-input bg-background px-2 text-sm"
          />
          <select
            aria-label="Who acts on the new item"
            value={who}
            onChange={(event) => setWho(event.target.value as Performer)}
            className="h-8 rounded-md border border-input bg-background px-2 text-sm"
          >
            {(Object.keys(PERFORMER_LABEL) as Performer[]).map((performer) => (
              <option key={performer} value={performer}>
                {PERFORMER_LABEL[performer]}
              </option>
            ))}
          </select>
          <Button
            type="button"
            size="sm"
            disabled={!name.trim()}
            onClick={() => {
              onAdd(name.trim(), who);
              setName("");
              setAdding(false);
            }}
          >
            Add
          </Button>
        </div>
      ) : null}
    </section>
  );
}

/** Where a plan item is (S3-01): the email it is in, or her task with "Mark done". */
function ItemWhere({
  item,
  onMarkDone,
  onOpenDraft,
}: {
  item: ConditionItem;
  onMarkDone?: (item: ConditionItem, done: boolean) => void;
  onOpenDraft?: (draftId: string) => void;
}) {
  const where = itemWhere(item);
  const draftId = item.draft?.id;
  // LP-942: an appraiser's ask is in the lender's email, and says why.
  const routeNote = item.route_note ? (
    <p className="text-xs text-muted-foreground">{item.route_note}</p>
  ) : null;
  if (where && draftId && onOpenDraft) {
    return (
      <>
        <button
          type="button"
          onClick={() => onOpenDraft(draftId)}
          className="inline-flex w-fit items-center gap-1 text-left text-xs text-primary hover:underline"
        >
          <Mail className="h-3 w-3" aria-hidden />
          {where}
        </button>
        {routeNote}
      </>
    );
  }
  if (where)
    return (
      <>
        <p className="text-xs text-primary">{where}</p>
        {routeNote}
      </>
    );
  if (item.option !== "i_will_do_it" || !onMarkDone) return null;
  const done = item.status === "done";
  return (
    <button
      type="button"
      onClick={() => onMarkDone(item, !done)}
      className="inline-flex w-fit items-center gap-1 text-xs text-primary hover:underline"
    >
      {done ? <Check className="h-3 w-3" aria-hidden /> : null}
      {done ? "Done — undo" : "Mark done"}
    </button>
  );
}

function joinCodes(codes: string[]): string {
  if (codes.length <= 1) return codes.join("");
  return `${codes.slice(0, -1).join(", ")} and ${codes[codes.length - 1]}`;
}

/** `Statement showing the funds before the check was written · Capital One ··9912 · Jul 2026`. */
function itemLine(item: ShownItem): string {
  const parts = [item.acceptable];
  const { account_bank: bank, account_last4: last4, month } = item.specifics;
  if (bank || last4) parts.push([bank, last4 ? `··${last4}` : null].filter(Boolean).join(" "));
  const monthText = monthLabel(month);
  if (monthText) parts.push(monthText);
  return parts.join(" · ");
}

/**
 * `27148.22` → `$27,148.22`, ON THE STRING. The server sends Decimal strings; going through `Number`
 * would put a computed figure through a float to print it, which is the one thing these figures are
 * promised never to do.
 */
function money(value: string): string {
  const [whole = "0", cents = "00"] = value.split(".");
  return `$${whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",")}.${cents.padEnd(2, "0").slice(0, 2)}`;
}

function lowerFirst(text: string): string {
  return text.charAt(0).toLowerCase() + text.slice(1);
}
