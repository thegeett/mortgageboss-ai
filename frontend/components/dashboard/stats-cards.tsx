"use client";

import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useLoanFiles } from "@/lib/api/loan-files";
import { statusesForFilter } from "@/lib/loan-files/status";
import type { FilterKey } from "@/lib/loan-files/status";
import { cn } from "@/lib/utils";
import { CircleAlert, CircleCheck, Files, FolderOpen } from "lucide-react";
import type { LucideIcon } from "lucide-react";

interface StatCard {
  key: FilterKey;
  label: string;
  icon: LucideIcon;
  iconClass: string;
}

// Counts are honest, exact totals: each card runs a tiny list query (page_size 1)
// for its grouping and reads the server-side `total`. Reuses the list endpoint —
// no fabricated numbers and no separate counts endpoint needed.
const CARDS: StatCard[] = [
  { key: "all", label: "Total files", icon: Files, iconClass: "text-gray-400" },
  { key: "active", label: "Active", icon: FolderOpen, iconClass: "text-primary" },
  { key: "action_needed", label: "Action needed", icon: CircleAlert, iconClass: "text-warning" },
  { key: "completed", label: "Completed", icon: CircleCheck, iconClass: "text-success" },
];

function StatTile({ card }: { card: StatCard }) {
  const { data, isPending, isError } = useLoanFiles({
    statuses: statusesForFilter(card.key),
    pageSize: 1,
  });

  return (
    <Card className="border-gray-200/80 p-4 shadow-sm">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-gray-500">{card.label}</span>
        <card.icon className={cn("h-4 w-4", card.iconClass)} />
      </div>
      {isPending ? (
        // Occupy the same box as the number line (mt-1 + the 3xl line height) so
        // the count arriving causes no vertical shift.
        <div className="mt-1 flex h-9 items-center" aria-busy>
          <span className="sr-only">Loading {card.label}</span>
          <Skeleton className="h-8 w-14" />
        </div>
      ) : (
        <p className="mt-1 text-3xl font-semibold tracking-tight text-gray-900">
          {isError ? "—" : (data?.total ?? 0)}
        </p>
      )}
    </Card>
  );
}

export function StatsCards() {
  return (
    <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
      {CARDS.map((card) => (
        <StatTile key={card.key} card={card} />
      ))}
    </div>
  );
}
