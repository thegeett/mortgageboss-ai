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
  /**
   * LP-858 §5 — whether ✦ polish is wired to anything (`email_draft_enabled`, off everywhere).
   *
   * THE BUTTON IS ABSENT WHEN THIS IS FALSE, not present and refusing. It used to render, be
   * pressed, and answer with a sentence naming the environment as the reason — which reads as
   * breakage rather than as a deliberate switch, and a processor cannot turn the switch on, so the
   * button could only ever disappoint them. The page's own principle at `communication/page.tsx`:
   * *"a processor cannot tell a feature that is broken from one that was never wired."*
   *
   * THAT SENTENCE IS NOT QUOTED ANYWHERE, deliberately. §9 checks for it with a grep over the
   * whole frontend, and a comment repeating it would keep the check red forever — the failure mode
   * the design file names about `needsClient`, one file over.
   */
  polish: boolean;
}

/**
 * FALSE WHILE LOADING AND FALSE ON ERROR, which `?? false` at the call site gives us.
 *
 * The safe default is the restrictive one. A panel that flashed into existence for a moment before
 * the answer arrived would be a control a processor could click, on a version where the thing
 * behind it does not exist; a panel that stays hidden because the request failed is a panel
 * missing, which is what this version looks like anyway.
 */
/**
 * ⚠️ UNDER `/api/v1`, LIKE EVERY OTHER ROUTE — AND IT WAS NOT. This asked for `/capabilities`, which
 * the server does not serve (`main.py` mounts the router under `API_V1_PREFIX`), so every request
 * 404'd and the fail-closed default above read BOTH switches as off on every deployment. Invisible
 * while both are off everywhere — which they are — and it would have hidden the inbound panel
 * (and S1-13 inside it) and polish on the first deployment that turned them on. Found in LP-909 §5's
 * Visual check, from the browser console.
 */
export async function fetchCapabilities(): Promise<Capabilities> {
  return (await apiClient.get<Capabilities>("/api/v1/capabilities")).data;
}

export function useCapabilities() {
  return useQuery({
    queryKey: ["capabilities"],
    queryFn: fetchCapabilities,
    // It changes on redeploy, never within a session.
    staleTime: Number.POSITIVE_INFINITY,
  });
}
