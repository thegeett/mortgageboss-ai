import { FolderOpen } from "lucide-react";

/**
 * Loan Files stub (LP-27). Exists so the nav item resolves to a real page; the
 * actual loan-file list/workspace is built in Epic 4. Renders inside the shell.
 */
export default function LoanFilesPage() {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold tracking-tight text-gray-900">Loan files</h2>
        <p className="mt-1 text-gray-500">Assemble, verify, and submit your loan files.</p>
      </div>

      <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-gray-300 bg-white px-6 py-16 text-center">
        <span className="flex h-12 w-12 items-center justify-center rounded-full bg-primary/10 text-primary">
          <FolderOpen className="h-6 w-6" />
        </span>
        <h3 className="mt-4 text-sm font-semibold text-gray-900">No loan files yet</h3>
        <p className="mt-1 max-w-sm text-sm text-gray-500">
          Loan-file management arrives in the next phase (Epic 4). This is where your files will
          live — intake to clear-to-close.
        </p>
      </div>
    </div>
  );
}
