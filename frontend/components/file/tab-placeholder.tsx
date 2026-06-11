import { Badge } from "@/components/ui/badge";
import type { LucideIcon } from "lucide-react";

/**
 * An intentional "coming in Phase X" placeholder for a not-yet-built file tab
 * (LP-33). Unmistakably upcoming — a dashed-border card with the phase badge —
 * never a broken or real-but-empty feature.
 */
export function TabPlaceholder({
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
    <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-gray-300 bg-white px-6 py-16 text-center">
      <span className="flex h-12 w-12 items-center justify-center rounded-full bg-gray-100 text-gray-400">
        <Icon className="h-6 w-6" />
      </span>
      <h2 className="mt-4 text-base font-semibold text-gray-900">{title}</h2>
      <Badge variant="secondary" className="mt-2 font-normal text-gray-500">
        Coming in {phase}
      </Badge>
      <p className="mt-3 max-w-sm text-sm text-gray-500">{description}</p>
    </div>
  );
}
