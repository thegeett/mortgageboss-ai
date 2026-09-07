import { redirect } from "next/navigation";

/**
 * `/` redirects to the dashboard (LP-UI-011, ADR-390).
 *
 * This was a 199-line developer splash: a backend health check and dependency
 * rows. It was never a processor screen and was deliberately never designed, so
 * the first thing anyone saw on opening the product was diagnostics.
 *
 * The page itself is not deleted — it is useful — it moved to `/dev/health`,
 * beside `/dev/extraction-bench`, which is where developer-only surfaces live.
 *
 * Sending `/` to `/dashboard` rather than to `/login` keeps one rule: the
 * protected layout decides who is allowed in, and it already redirects an
 * unauthenticated visitor to `/login` after the silent refresh settles. Sending
 * `/` straight to `/login` would bounce a signed-in user through a login screen
 * they do not need.
 */
export default function RootPage() {
  redirect("/dashboard");
}
