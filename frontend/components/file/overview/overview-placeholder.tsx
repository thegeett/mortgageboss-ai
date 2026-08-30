import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import type { LucideIcon } from "lucide-react";

/**
 * A small, card-sized "coming in Phase X" placeholder for an overview section
 * that isn't built yet (LP-34) — intentional, never a broken/empty feature.
 */
export function OverviewPlaceholder({
  title,
  phase,
  description,
  icon: Icon,
}: {
  title: string;
  phase: string;
  description: string;
  icon: LucideIcon;
}) {
  return (
    <Card className="border-dashed border-input bg-card shadow-none">
      <CardContent className="flex items-start gap-3 p-4">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-muted text-muted-foreground">
          <Icon className="h-4 w-4" />
        </span>
        <div>
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-semibold text-foreground">{title}</h3>
            <Badge
              variant="secondary"
              className="px-1.5 py-0 text-[10px] font-normal text-muted-foreground"
            >
              Coming in {phase}
            </Badge>
          </div>
          <p className="mt-1 text-sm text-muted-foreground">{description}</p>
        </div>
      </CardContent>
    </Card>
  );
}
