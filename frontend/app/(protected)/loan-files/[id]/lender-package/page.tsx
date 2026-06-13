import { TabPlaceholder } from "@/components/file/tab-placeholder";
import { PackageCheck } from "lucide-react";

export default function LenderPackagePage() {
  return (
    <TabPlaceholder
      title="Lender Package"
      phase="Phase 6"
      description="Assemble and submit the complete, verified package to the lender's underwriting."
      icon={PackageCheck}
    />
  );
}
