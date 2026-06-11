import { TabPlaceholder } from "@/components/file/tab-placeholder";
import { FolderOpen } from "lucide-react";

export default function DocumentsPage() {
  return (
    <TabPlaceholder
      title="Documents"
      phase="Phase 2 (Epic 5)"
      description="Upload, classify, and extract data from the file's documents. This is where the document workspace will live."
      icon={FolderOpen}
    />
  );
}
