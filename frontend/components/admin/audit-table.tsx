"use client";

import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { auditTimeLabel } from "@/lib/admin-time";
import { useAuditLog } from "@/lib/api/audit-log";
import type { AuditChange, AuditEntry, AuditFilters, Person } from "@/lib/types/users";
import { useMemo, useState } from "react";

/**
 * The company audit log (LP-MB-Admin-03, mockup 12): When, Who, What, Change.
 *
 * Three plain selects filter it (what kind of target, who acted, how far back) and Load more
 * follows the server's cursor. Read-only. No export yet.
 */

const SPANS = { "30": "Last 30 days", "7": "Last 7 days", all: "All time" } as const;
type Span = keyof typeof SPANS;

/** One value as the Change column shows it: a list joined, a flag as on/off, nothing as "—". */
function shown(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (Array.isArray(value)) return value.length ? value.map(shown).join(", ") : "none";
  if (typeof value === "boolean") return value ? "on" : "off";
  return String(value);
}

function ChangeCell({ changes }: { changes: AuditChange[] | undefined }) {
  if (!changes || changes.length === 0) return <span className="text-muted-foreground">—</span>;
  return (
    <ul className="space-y-0.5 font-mono text-xs">
      {changes.map((change) => (
        <li key={change.field}>
          {changes.length > 1 ? (
            <span className="text-muted-foreground">{change.field.replaceAll("_", " ")}: </span>
          ) : null}
          <span className="text-muted-foreground">{shown(change.from)}</span> →{" "}
          <span className="text-foreground">{shown(change.to)}</span>
        </li>
      ))}
    </ul>
  );
}

export function AuditTable({ people }: { people: Person[] }) {
  const [targetType, setTargetType] = useState("");
  const [actor, setActor] = useState("");
  const [span, setSpan] = useState<Span>("30");
  // Fixed while the filter is unchanged, so the query key (and its pages) stays stable.
  const filters = useMemo<AuditFilters>(() => {
    const since =
      span === "all"
        ? undefined
        : new Date(Date.now() - Number(span) * 24 * 60 * 60 * 1000).toISOString();
    return {
      ...(targetType ? { target_type: targetType } : {}),
      ...(actor ? { actor_user_id: actor } : {}),
      ...(since ? { since } : {}),
    };
  }, [targetType, actor, span]);
  const log = useAuditLog(filters);

  const entries: AuditEntry[] = log.data?.pages.flatMap((page) => page.items) ?? [];
  const total = log.data?.pages[0]?.total ?? 0;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-3">
        <Select
          aria-label="What"
          className="w-40"
          value={targetType}
          onChange={(event) => setTargetType(event.target.value)}
        >
          <option value="">Anything</option>
          <option value="user">People</option>
          <option value="company">Company settings</option>
        </Select>
        <Select
          aria-label="Who"
          className="w-44"
          value={actor}
          onChange={(event) => setActor(event.target.value)}
        >
          <option value="">Anyone</option>
          {people.map((person) => (
            <option key={person.id} value={person.id}>
              {person.first_name} {person.last_name}
            </option>
          ))}
        </Select>
        <Select
          aria-label="When"
          className="w-40"
          value={span}
          onChange={(event) => setSpan(event.target.value as Span)}
        >
          {(Object.keys(SPANS) as Span[]).map((key) => (
            <option key={key} value={key}>
              {SPANS[key]}
            </option>
          ))}
        </Select>
      </div>

      {log.isPending ? (
        <p className="text-sm text-muted-foreground" aria-busy>
          Loading…
        </p>
      ) : log.isError ? (
        <p className="text-sm text-muted-foreground" role="alert">
          The audit log is unavailable.
        </p>
      ) : (
        <>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>When</TableHead>
                <TableHead>Who</TableHead>
                <TableHead>What</TableHead>
                <TableHead>Change</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {entries.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={4} className="text-sm text-muted-foreground">
                    Nothing recorded for these filters.
                  </TableCell>
                </TableRow>
              ) : (
                entries.map((entry) => (
                  <TableRow key={entry.id}>
                    <TableCell className="whitespace-nowrap text-muted-foreground">
                      {auditTimeLabel(entry.created_at)}
                    </TableCell>
                    <TableCell className={entry.actor ? "" : "text-muted-foreground"}>
                      {entry.actor?.name ?? "System"}
                    </TableCell>
                    <TableCell>{entry.summary}</TableCell>
                    <TableCell>
                      <ChangeCell changes={entry.detail.changes} />
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
          <div className="flex items-center justify-between">
            <p className="text-xs text-muted-foreground">
              {entries.length} of {total}
            </p>
            {log.hasNextPage ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={log.isFetchingNextPage}
                onClick={() => log.fetchNextPage()}
              >
                {log.isFetchingNextPage ? "Loading…" : "Load more"}
              </Button>
            ) : null}
          </div>
        </>
      )}
    </div>
  );
}
