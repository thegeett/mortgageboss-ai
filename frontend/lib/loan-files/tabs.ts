/**
 * File-detail tab configuration (LP-33).
 *
 * All six tabs are shown; the ones whose features aren't built yet carry a
 * `phase` and render a clearly-labeled "coming in Phase X" placeholder. Unlike
 * top-level nav (where phantom items mislead about app capability), labeled file
 * tabs honestly convey the file's processing lifecycle (ADR).
 */
export interface FileTab {
  key: string;
  label: string;
  /** URL segment under `/loan-files/{id}`; "" is the default Overview tab. */
  segment: string;
  /** The phase a not-yet-built tab arrives in; undefined for Overview. */
  phase?: string;
}

export const FILE_TABS: FileTab[] = [
  { key: "overview", label: "Overview", segment: "" },
  { key: "documents", label: "Documents", segment: "documents", phase: "Phase 2 (Epic 5)" },
  { key: "verification", label: "Verification", segment: "verification", phase: "Phase 3" },
  { key: "communication", label: "Communication", segment: "communication", phase: "Phase 4" },
  { key: "conditions", label: "Conditions", segment: "conditions", phase: "Phase 4.5" },
  {
    key: "lender-package",
    label: "Lender Package",
    segment: "lender-package",
    phase: "Phase 6",
  },
];

const TAB_SEGMENTS = new Set(FILE_TABS.map((tab) => tab.segment).filter(Boolean));

/**
 * The active tab key for a pathname. The last path segment is a tab segment for
 * the non-overview tabs (`/loan-files/LF-X/documents`); anything else — including
 * the bare `/loan-files/LF-X` — is the Overview tab.
 */
export function activeTabKey(pathname: string): string {
  const last = pathname.split("/").filter(Boolean).pop() ?? "";
  if (TAB_SEGMENTS.has(last)) {
    return FILE_TABS.find((tab) => tab.segment === last)?.key ?? "overview";
  }
  return "overview";
}

/** Build the href for a tab under a given file. */
export function tabHref(fileId: string, segment: string): string {
  const base = `/loan-files/${fileId}`;
  return segment === "" ? base : `${base}/${segment}`;
}
