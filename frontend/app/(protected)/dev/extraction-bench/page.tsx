"use client";

import {
  type BenchPreview,
  type BenchStatus,
  benchStatus,
  cancelBench,
  previewBench,
  startBench,
} from "@/lib/api/extraction-bench";
import { FlaskConical } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Extraction bench (DEV-ONLY). Runs a folder of real documents through the LIVE classification +
 * extraction pipeline and reports what the schemas actually capture — it MEASURES COVERAGE, NOT
 * ACCURACY, and persists NOTHING to the database.
 *
 * Gating is defence-in-depth: the backend router is absent (404) outside development, and this page
 * also refuses to render its controls in a production build. PII is placeholder-redacted in two
 * layers before anything is written to disk. See docs/tickets/extraction-bench.md.
 *
 * The flow is deliberate: PREVIEW first (count, breakdown, unreadable, estimated cost) — nothing runs
 * and no model is called — then an explicit Start. A run is pollable and interruptible.
 */
export default function ExtractionBenchPage() {
  const isProd = process.env.NODE_ENV === "production";

  const [root, setRoot] = useState("");
  const [preview, setPreview] = useState<BenchPreview | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [runId, setRunId] = useState<string | null>(null);
  const [status, setStatus] = useState<BenchStatus | null>(null);
  const [starting, setStarting] = useState(false);
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearTimeout(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const poll = useCallback(async (id: string) => {
    try {
      const s = await benchStatus(id);
      setStatus(s);
      if (!s.finished) {
        pollRef.current = setTimeout(() => void poll(id), 1500);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "status poll failed");
    }
  }, []);

  useEffect(() => stopPolling, [stopPolling]);

  async function onPreview() {
    setError(null);
    setPreview(null);
    setStatus(null);
    setRunId(null);
    setPreviewing(true);
    try {
      setPreview(await previewBench(root.trim()));
    } catch (e) {
      setError(e instanceof Error ? e.message : "preview failed");
    } finally {
      setPreviewing(false);
    }
  }

  async function onStart() {
    setError(null);
    setStarting(true);
    try {
      const s = await startBench(root.trim());
      setRunId(s.run_id);
      void poll(s.run_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "start failed");
    } finally {
      setStarting(false);
    }
  }

  async function onCancel() {
    if (!runId) return;
    try {
      setStatus(await cancelBench(runId));
    } catch (e) {
      setError(e instanceof Error ? e.message : "cancel failed");
    }
  }

  if (isProd) {
    return (
      <div className="rounded-lg border border-dashed border-gray-300 bg-white px-6 py-16 text-center text-sm text-gray-500">
        The extraction bench is a development-only tool and is unavailable in this environment.
      </div>
    );
  }

  const running = runId !== null && status !== null && !status.finished;
  const pct = status && status.total > 0 ? Math.round((status.done / status.total) * 100) : 0;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="flex items-center gap-2 text-2xl font-bold tracking-tight text-gray-900">
          <FlaskConical className="h-6 w-6 text-primary" />
          Extraction bench
        </h2>
        <p className="mt-1 text-gray-500">
          Run a folder of real documents through the live classification + extraction pipeline and
          see what the schemas actually capture. Measures <strong>coverage, not accuracy</strong> —
          writes JSON to disk and persists <strong>nothing</strong> to the database. PII is
          placeholder-redacted.
        </p>
      </div>

      {/* Folder + preview */}
      <div className="space-y-3 rounded-lg border border-gray-200 bg-white p-5">
        <label htmlFor="root" className="block text-sm font-medium text-gray-900">
          Document folder (absolute path on the backend host)
        </label>
        <div className="flex gap-2">
          <input
            id="root"
            type="text"
            value={root}
            onChange={(e) => setRoot(e.target.value)}
            placeholder="/path/to/real/documents"
            disabled={running}
            className="flex-1 rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-900 focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary disabled:bg-gray-50"
          />
          <button
            type="button"
            onClick={onPreview}
            disabled={!root.trim() || previewing || running}
            className="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-900 hover:bg-gray-50 disabled:opacity-50"
          >
            {previewing ? "Previewing…" : "Preview"}
          </button>
        </div>
        <p className="text-xs text-gray-500">
          Nothing runs on preview — it only counts files and estimates cost. No model is called.
        </p>
      </div>

      {error && (
        <div className="rounded-md border border-danger/30 bg-danger/5 px-4 py-3 text-sm text-danger">
          {error}
        </div>
      )}

      {/* Preview result + Start */}
      {preview && (
        <div className="space-y-4 rounded-lg border border-gray-200 bg-white p-5">
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <Stat label="Files found" value={String(preview.total)} />
            <Stat label="Readable" value={String(preview.readable)} />
            <Stat label="Unreadable" value={String(preview.unreadable.length)} />
            <Stat label="Est. cost" value={`$${preview.estimated_cost.toFixed(2)}`} />
          </div>

          <div className="text-xs text-gray-500">
            {preview.provider} · {preview.extraction_model} · ${preview.per_doc_estimate.toFixed(3)}
            /doc
          </div>

          {Object.keys(preview.by_extension).length > 0 && (
            <div className="flex flex-wrap gap-2">
              {Object.entries(preview.by_extension).map(([ext, n]) => (
                <span
                  key={ext}
                  className="rounded-full bg-gray-100 px-2.5 py-1 text-xs font-medium text-gray-700"
                >
                  {ext} · {n}
                </span>
              ))}
            </div>
          )}

          {preview.unreadable.length > 0 && (
            <details className="text-xs text-gray-600">
              <summary className="cursor-pointer font-medium text-warning">
                {preview.unreadable.length} unreadable — skipped
              </summary>
              <ul className="mt-2 space-y-1">
                {preview.unreadable.map((u) => (
                  <li key={u.file} className="font-mono">
                    {u.file} — {u.reason}
                  </li>
                ))}
              </ul>
            </details>
          )}

          <div className="flex items-center gap-3 border-t border-gray-100 pt-4">
            <button
              type="button"
              onClick={onStart}
              disabled={starting || running || preview.readable === 0}
              className="rounded-md bg-primary px-4 py-2 text-sm font-semibold text-white hover:bg-primary/90 disabled:opacity-50"
            >
              {starting ? "Starting…" : `Start — run ${preview.readable} documents`}
            </button>
            <span className="text-xs text-gray-500">
              This calls the model on every readable document (~${preview.estimated_cost.toFixed(2)}
              ).
            </span>
          </div>
        </div>
      )}

      {/* Run progress */}
      {status && (
        <div className="space-y-3 rounded-lg border border-gray-200 bg-white p-5">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-gray-900">
              {status.finished ? (status.cancelled ? "Cancelled" : "Finished") : "Running…"}
            </h3>
            {running && (
              <button
                type="button"
                onClick={onCancel}
                className="rounded-md border border-gray-300 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50"
              >
                Cancel
              </button>
            )}
          </div>

          <div className="h-2 w-full overflow-hidden rounded-full bg-gray-100">
            <div
              className="h-full rounded-full bg-primary transition-all"
              style={{ width: `${pct}%` }}
            />
          </div>

          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-gray-600">
            <span>
              {status.done}/{status.total} documents
            </span>
            <span>cost so far ${status.cost_so_far.toFixed(2)}</span>
            {status.current && <span className="font-mono">{status.current}</span>}
          </div>

          {status.finished && (
            <p className="text-xs text-gray-500">
              Output written to <span className="font-mono">{status.output_dir}</span> —{" "}
              <span className="font-mono">_SUMMARY.md</span>,{" "}
              <span className="font-mono">_FINDINGS.csv</span>, and per-document JSON.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-2xl font-bold text-gray-900">{value}</div>
      <div className="text-xs uppercase tracking-wide text-gray-500">{label}</div>
    </div>
  );
}
