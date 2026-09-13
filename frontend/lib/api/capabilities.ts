import { apiClient } from "@/lib/api/client";
import { useQuery } from "@tanstack/react-query";

/**
 * What this deployment can do (LP-857).
 *
 * READ FROM THE SERVER, NOT FROM A BUILD-TIME CONSTANT. The same flag decides whether the
 * Communication page offers the upload and inbound panels AND whether a generated request promises
 * a borrower an upload link — and the second is decided on the server when the body is rendered. A
 * `NEXT_PUBLIC_` twin would let a deployment hide the panel and keep the promise, which is the
 * failure this ticket removes rather than a new place to introduce it.
 */
export interface Capabilities {
  /**
   * Both ways a document comes back IN: the secure upload link (LP-815) and inbound mail (LP-807).
   * Off in v1 — *"No receiving, sending, secure upload link, reply email and all. We will do it in
   * next phase."*
   */
  receiving: boolean;
}

/**
 * FALSE WHILE LOADING AND FALSE ON ERROR, which `?? false` at the call site gives us.
 *
 * The safe default is the restrictive one. A panel that flashed into existence for a moment before
 * the answer arrived would be a control a processor could click, on a version where the thing
 * behind it does not exist; a panel that stays hidden because the request failed is a panel
 * missing, which is what this version looks like anyway.
 */
export function useCapabilities() {
  return useQuery({
    queryKey: ["capabilities"],
    queryFn: async () => (await apiClient.get<Capabilities>("/capabilities")).data,
    // It changes on redeploy, never within a session.
    staleTime: Number.POSITIVE_INFINITY,
  });
}
