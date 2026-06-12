/** Activity-log entry (LP-34), mirroring the backend `ActivityPublic`. */

export type ActivityType =
  | "file_created"
  | "file_updated"
  | "file_deleted"
  | "status_changed"
  | "document_uploaded"
  | "document_processed"
  | "finding_resolved"
  | "verification_run"
  | "needs_item_created"
  | "needs_item_satisfied"
  | "communication_sent"
  | "communication_received"
  | "note_added";

export interface ActivityPublic {
  id: string;
  activity_type: ActivityType;
  summary: string;
  actor_user_id: string | null;
  detail: Record<string, unknown>;
  created_at: string;
}
