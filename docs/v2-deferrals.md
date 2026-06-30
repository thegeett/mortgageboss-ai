# V1 Boundaries — what's explicitly deferred to V2 (LP-89)

The honest record of what V1 deliberately does NOT do, so the boundaries are explicit (not gaps
discovered later). Each is a considered deferral, not an oversight.

## Verification / rules / calculators

- **Domain validation of the rules + calculator methodologies.** Every rule (LP-82..86) and
  calculator methodology (LP-87) is a **grounded starter** — researched but not validated by Priya.
  V1 ships the validation AID (LP-89); the actual validation is her session + the follow-up corrections.
- **Auto-detected compensating factors (FHA).** The FHA compensating-factors model (LP-84) and the
  subject-to-repair conditional findings (LP-85) are MITIGABLE — the human DOCUMENTS the compensating
  factor / the repair (Accept-risk) and the system records it. V1 does NOT auto-detect or auto-apply
  compensating factors; that's domain judgment.
- **Auto-re-run of verification.** Verification is a MANUAL trigger (the AI cross-source pass is a cost
  + latency). Edits mark it stale (a prompt to re-run); V1 does not auto-run on every change.
- **Live engine reads of DB overlays.** The overlay admin (LP-87) edits a company's overlay store and
  makes the effect legible; wiring the LIVE engine/calculators to prefer a company's DB overlay over
  the in-code starter overlays (so admin edits drive enforcement end-to-end) is V2.

## Source location / extraction

- **Bounding boxes.** Source location is page + verbatim snippet (the trust anchor), NOT pixel-precise
  bounding boxes / highlight overlays. V2.
- **A `source_finding_id` FK** from a needs item to a verification finding (Request-docs links by
  reasoning text + the finding's `docs_requested` marker today; a direct FK is V2).

## Infrastructure / ops

- **S3 / MinIO object-storage validation.** Document storage runs on the local backend in dev; validate
  the S3/MinIO object-storage path before a production deploy.
- **Hard-delete admin work (LP-79.5 deferral).** Soft-delete is the model everywhere; the admin
  hard-delete + a restore/trash view are deferred.

## Communication (Phase 4)

- **Full borrower communication.** Request-docs (LP-88) creates a needs item (the seam); the full
  communication flow (sending the request, tracking the reply, the email integration) is Phase 4.

## Watchdog note (LP-89)

The stuck-RUNNING watchdog reconciles a dead run to FAILED on read (a 5-minute timeout > the task hard
limit). A periodic Celery-beat sweep (so a never-read file's stuck run is also reconciled) is a small
V2 follow-up; the read-time reconcile covers the demo + the normal path.
