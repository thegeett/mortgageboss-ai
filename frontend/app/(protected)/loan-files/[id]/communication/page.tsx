import { TabPlaceholder } from "@/components/file/tab-placeholder";
import { MessagesSquare } from "lucide-react";

export default function CommunicationPage() {
  return (
    <TabPlaceholder
      title="Communication"
      phase="Phase 4"
      description="Borrower and lender messages for this file — document requests, replies, and the timeline."
      icon={MessagesSquare}
    />
  );
}
