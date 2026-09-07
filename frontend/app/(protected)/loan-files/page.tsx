import { redirect } from "next/navigation";

/**
 * `/loan-files` redirects to the dashboard (LP-UI-011).
 *
 * This route used to be a stub that said loan-file management "arrives in the
 * next phase (Epic 4)". Epic 4 arrived: the dashboard is the list, with search,
 * filters and the pipeline table. The redirect exists so a bookmark or a link
 * from before still lands somewhere useful rather than 404ing.
 *
 * `/loan-files/[id]` is untouched — the prefix is still the file workspace.
 */
export default function LoanFilesIndex() {
  redirect("/dashboard");
}
