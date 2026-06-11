import { TabPlaceholder } from "@/components/file/tab-placeholder";
import { ShieldCheck } from "lucide-react";

export default function VerificationPage() {
  return (
    <TabPlaceholder
      title="Verification"
      phase="Phase 3"
      description="Automated checks across the file's data and documents — red/yellow/green findings and their resolution."
      icon={ShieldCheck}
    />
  );
}
