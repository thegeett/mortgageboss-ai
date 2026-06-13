import { ErrorBoundary } from "@/components/error-boundary";
import { Header } from "@/components/layout/header";
import { Sidebar } from "@/components/layout/sidebar";

/**
 * The authenticated app shell (LP-27): a persistent sidebar + header framing the
 * scrollable content area. Every page in the `(protected)` route group renders
 * into `children`, so the chrome is defined once here.
 *
 * The content area is wrapped in its own error boundary (LP-46) so a crash in a
 * page keeps the sidebar/header usable — the user can navigate away or retry the
 * content without losing the whole app.
 */
export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-screen overflow-hidden bg-gray-50">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <Header />
        <main className="flex-1 overflow-y-auto">
          <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6 lg:px-8">
            <ErrorBoundary>{children}</ErrorBoundary>
          </div>
        </main>
      </div>
    </div>
  );
}
