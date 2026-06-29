/**
 * Overlay admin types (LP-87) — mirror the backend overlay-admin schemas.
 * The admin UI views/edits a lender's overlay (LP-80's storage) with the effect made
 * legible (base default → overlay effective) and the from→to audit trail.
 */

export interface OverlayOverrideView {
  rule_id: string;
  rule_description: string;
  op: string;
  unit: string | null;
  base_value: string | null;
  effective_value: string;
  reason: string | null;
}

export interface OverlayAuditEntry {
  at: string;
  actor_user_id: string | null;
  reason: string;
  changes: { field: string; from: string | null; to: string | null }[];
}

export interface LenderOverlayView {
  id: string;
  name: string;
  slug: string;
  overrides: OverlayOverrideView[];
  audit: OverlayAuditEntry[];
}

export interface OverlayOverrideInput {
  rule_id: string;
  value: string;
  reason?: string | null;
}

export interface OverlayUpdateRequest {
  overrides: OverlayOverrideInput[];
  reason: string;
}
