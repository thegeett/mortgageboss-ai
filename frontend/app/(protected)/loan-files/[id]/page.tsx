import { TabPlaceholder } from "@/components/file/tab-placeholder";
import { FileText } from "lucide-react";

/**
 * Overview tab (default). Placeholder for now — LP-34 fills it with the file
 * summary (borrowers, property, loan, needs list).
 */
export default function OverviewPage() {
  return (
    <TabPlaceholder
      title="Overview"
      phase="the next step (LP-34)"
      description="A summary of this file — borrowers, property, loan terms, and the needs list — lands here next."
      icon={FileText}
    />
  );
}
