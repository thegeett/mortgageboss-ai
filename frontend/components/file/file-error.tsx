import { Button } from "@/components/ui/button";
import { FileQuestion, RotateCw, TriangleAlert } from "lucide-react";
import Link from "next/link";

/**
 * The not-found / error state for a file (LP-33, retry added LP-46). A 404
 * (missing *or* out-of-company — both are tenant-safe and surface the same)
 * shows "File not found" with a way back; any other (transient) error shows a
 * clean message with a Retry plus the way back.
 */
export function FileError({ notFound, onRetry }: { notFound: boolean; onRetry?: () => void }) {
  const showRetry = !notFound && onRetry !== undefined;
  return (
    <div className="flex flex-col items-center justify-center px-6 py-20 text-center">
      <span className="flex h-12 w-12 items-center justify-center rounded-full bg-gray-100 text-gray-400">
        {notFound ? (
          <FileQuestion className="h-6 w-6" />
        ) : (
          <TriangleAlert className="h-6 w-6 text-destructive" />
        )}
      </span>
      <h1 className="mt-4 text-lg font-semibold text-gray-900">
        {notFound ? "File not found" : "Couldn't load this file"}
      </h1>
      <p className="mt-1 max-w-sm text-sm text-gray-500">
        {notFound
          ? "This loan file doesn't exist, or you don't have access to it."
          : "Something went wrong loading this file. Check your connection and try again."}
      </p>
      <div className="mt-5 flex items-center gap-3">
        {showRetry && (
          <Button type="button" onClick={onRetry} className="gap-1.5">
            <RotateCw className="h-4 w-4" />
            Retry
          </Button>
        )}
        <Button asChild variant={showRetry ? "outline" : "default"}>
          <Link href="/dashboard">Back to dashboard</Link>
        </Button>
      </div>
    </div>
  );
}
