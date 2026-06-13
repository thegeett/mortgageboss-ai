import { TabPlaceholder } from "@/components/file/tab-placeholder";
import { ListChecks } from "lucide-react";

export default function ConditionsPage() {
  return (
    <TabPlaceholder
      title="Conditions"
      phase="Phase 4.5"
      description="Underwriting conditions on the file — tracking and clearing each one toward clear-to-close."
      icon={ListChecks}
    />
  );
}
