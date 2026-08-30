"use client";

import { NeedsDashboard } from "@/components/file/needs/needs-dashboard";
import { useParams } from "next/navigation";

/**
 * Needs — its own route (LP-UI-022).
 *
 * The self-maintaining checklist is the product's differentiator and it was the
 * third section on a page about something else, between the stated financials and
 * the activity feed. It gets the room to say what each need is, where it came
 * from, and how much to trust it: a deterministic baseline requirement reads
 * differently from the AI's reading of a document, and an AI proposal is never
 * acted on until a processor confirms it.
 *
 * The Overview keeps a compact summary that links here, so opening a file still
 * says how much is outstanding without the list taking the page over.
 */
export default function NeedsPage() {
  const { id } = useParams<{ id: string }>();
  return <NeedsDashboard fileId={id} />;
}
