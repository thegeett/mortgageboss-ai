import type { ConditionGroupBy } from "@/lib/conditions/list-url";
import { OWNER_LABEL } from "@/lib/conditions/owners";
import { CONDITION_PREP_STATUS } from "@/lib/status";
import type { Condition } from "@/lib/types/conditions";

/** The label a row is grouped under. */
export function groupKeyOf(condition: Condition, groupBy: ConditionGroupBy): string {
  if (groupBy === "owner") return OWNER_LABEL[condition.effective_owner];
  if (groupBy === "prep_status") return CONDITION_PREP_STATUS[condition.prep_status].label;
  return condition.bucket_heading || "No heading given";
}

/**
 * The list's groups, rows in sheet order inside each (LP-913).
 *
 * TWO SHAPES, BECAUSE THE GROUPINGS MEAN DIFFERENT THINGS (LP-913 review). By HEADING, a group is a
 * RUN of rows: the lender's headings are sections of the sheet, one heading can own two runs (a
 * hand-typed condition between two printed ones), and keying by heading alone raised a React
 * duplicate-key error per repeat (LP-909 §5). By OWNER or by OUR STATUS, a group is every row with
 * that value. The first version used runs for all three, so on round 1 "Group by: waiting on" drew
 * Title twice — `1947` and `6378` are printed with processor rows between them.
 *
 * Groups appear in the order their first row is printed.
 */
export function groupConditions(
  rows: Condition[],
  groupBy: ConditionGroupBy,
): { key: string; rows: Condition[] }[] {
  const bySequence = [...rows].sort((a, b) => a.sequence - b.sequence);
  const groups: { key: string; rows: Condition[] }[] = [];
  if (groupBy === "heading") {
    for (const condition of bySequence) {
      const key = groupKeyOf(condition, groupBy);
      const last = groups.at(-1);
      if (last && last.key === key) last.rows.push(condition);
      else groups.push({ key, rows: [condition] });
    }
    return groups;
  }
  const byKey = new Map<string, Condition[]>();
  for (const condition of bySequence) {
    const key = groupKeyOf(condition, groupBy);
    const existing = byKey.get(key);
    if (existing) existing.push(condition);
    else {
      const fresh = [condition];
      byKey.set(key, fresh);
      groups.push({ key, rows: fresh });
    }
  }
  return groups;
}
