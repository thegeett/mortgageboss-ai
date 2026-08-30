"use client";

import {
  type BenchPreview,
  type BenchStatus,
  benchStatus,
  cancelBench,
  previewBench,
  startBench,
} from "@/lib/api/extraction-bench";
import { isAxiosError } from "axios";
import { FlaskConical } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

/** Surface the backend's error detail (e.g. the 409 "refusing to start — unpaced" message), not a bare "Request failed". */
function errMsg(e: unknown, fallback: string): string {
  if (isAxiosError(e)) {
    const detail = e.response?.data?.detail;
    if (typeof detail === "string") return detail;
  }
  return e instanceof Error ? e.message : fallback;
}

/**
 * Extraction bench (DEV-ONLY). Runs a folder of real documents through the LIVE classification +
 * extraction pipeline and reports what the schemas actually capture — it MEASURES COVERAGE, NOT
 * ACCURACY, and persists NOTHING to the database.
 *
 * Gating is defence-in-depth: the backend router is absent (404) outside development, and this page
 * also refuses to render its controls in a production build. ⚠️ Redaction was REMOVED — the output
 * captures REAL PII and must not be committed/shared/moved. See docs/tickets/extraction-bench.md.
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
      setError(errMsg(e, "preview failed"));
    } finally {
      setPreviewing(false);
    }
  }

  async function onStart(resumeRunId?: string) {
    setError(null);
    setStarting(true);
    try {
      const s = await startBench(root.trim(), resumeRunId);
      setRunId(s.run_id);
      setStatus(null);
      void poll(s.run_id);
    } catch (e) {
      setError(errMsg(e, "start failed"));
    } finally {
      setStarting(false);
    }
  }

  async function onCancel() {
    if (!runId) return;
    try {
      setStatus(await cancelBench(runId));
    } catch (e) {
      setError(errMsg(e, "cancel failed"));
    }
  }

  if (isProd) {
    return (
      <div className="rounded-lg border border-dashed border-input bg-card px-6 py-16 text-center text-sm text-muted-foreground">
        The extraction bench is a development-only tool and is unavailable in this environment.
      </div>
    );
  }

  const running = runId !== null && status !== null && !status.finished;
  const pct = status && status.total > 0 ? Math.round((status.done / status.total) * 100) : 0;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="flex items-center gap-2 text-2xl font-semibold tracking-tight text-foreground">
          <FlaskConical className="h-6 w-6 text-primary" />
          Extraction bench
        </h2>
        <p className="mt-1 text-muted-foreground">
          Run a folder of real documents through the live classification + extraction pipeline and
          see what the schemas actually capture. Measures <strong>coverage, not accuracy</strong> —
          writes JSON to disk and persists <strong>nothing</strong> to the database.
        </p>
      </div>

      {/* REAL-PII warning — redaction was removed; the output captures real borrower PII */}
      <div className="rounded-md border border-danger/40 bg-danger/5 px-4 py-3 text-sm text-danger">
        🔴 <strong>This run captures REAL PII</strong> — real SSNs, dates of birth, home addresses,
        and account numbers are written to the output folder. It{" "}
        <strong>must not be committed, shared, or moved off this machine</strong>.
      </div>

      {/* Folder + preview */}
      <div className="space-y-3 rounded-lg border border-border bg-card p-5">
        <label htmlFor="root" className="block text-sm font-medium text-foreground">
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
            className="flex-1 rounded-md border border-input px-3 py-2 text-sm text-foreground focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary disabled:bg-muted"
          />
          <button
            type="button"
            onClick={onPreview}
            disabled={!root.trim() || previewing || running}
            className="rounded-md border border-input bg-card px-4 py-2 text-sm font-medium text-foreground hover:bg-muted disabled:opacity-50"
          >
            {previewing ? "Previewing…" : "Preview"}
          </button>
        </div>
        <p className="text-xs text-muted-foreground">
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
        <div className="space-y-4 rounded-lg border border-border bg-card p-5">
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <Stat label="Files found" value={String(preview.total)} />
            <Stat label="Readable" value={String(preview.readable)} />
            <Stat label="Unreadable" value={String(preview.unreadable.length)} />
            <Stat label="Est. cost" value={`$${preview.estimated_cost.toFixed(2)}`} />
          </div>

          <div className="text-xs text-muted-foreground">
            {preview.provider} · {preview.extraction_model} · ${preview.per_doc_estimate.toFixed(3)}
            /doc
          </div>

          {/* Pacing — surfaced before Start so a multi-hour or unpaced run is never a surprise */}
          {preview.requests_per_minute != null ? (
            <div className="text-xs text-muted-foreground">
              Paced at {preview.requests_per_minute} requests/min (2 calls/doc) · est.{" "}
              <strong>~{preview.estimated_minutes} min</strong> for {preview.readable} documents
            </div>
          ) : preview.provider === "bedrock" ? (
            <div className="rounded-md border border-danger/30 bg-danger/5 px-3 py-2 text-xs text-danger">
              ⚠️ No rate limit set under Bedrock — the bench will <strong>refuse to start</strong>.
              Set <span className="font-mono">AI_REQUESTS_PER_MINUTE_BEDROCK</span> (e.g. 8) and
              re-preview.
            </div>
          ) : (
            <div className="text-xs text-muted-foreground">
              Unpaced (no request limit configured).
            </div>
          )}

          {Object.keys(preview.by_extension).length > 0 && (
            <div className="flex flex-wrap gap-2">
              {Object.entries(preview.by_extension).map(([ext, n]) => (
                <span
                  key={ext}
                  className="rounded-full bg-muted px-2.5 py-1 text-xs font-medium text-foreground-2"
                >
                  {ext} · {n}
                </span>
              ))}
            </div>
          )}

          {preview.unreadable.length > 0 && (
            <details className="text-xs text-foreground-2">
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

          <div className="flex items-center gap-3 border-t border-border pt-4">
            <button
              type="button"
              onClick={() => onStart()}
              disabled={starting || running || preview.readable === 0}
              className="rounded-md bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            >
              {starting ? "Starting…" : `Start — run ${preview.readable} documents`}
            </button>
            <span className="text-xs text-muted-foreground">
              This calls the model on every readable document (~${preview.estimated_cost.toFixed(2)}
              ).
            </span>
          </div>
        </div>
      )}

      {/* Run progress */}
      {status && (
        <div className="space-y-3 rounded-lg border border-border bg-card p-5">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-foreground">
              {status.finished ? (status.cancelled ? "Cancelled" : "Finished") : "Running…"}
            </h3>
            {running && (
              <button
                type="button"
                onClick={onCancel}
                className="rounded-md border border-input px-3 py-1.5 text-xs font-medium text-foreground-2 hover:bg-muted"
              >
                Cancel
              </button>
            )}
          </div>

          <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
            <div
              className="h-full rounded-full bg-primary transition-all"
              style={{ width: `${pct}%` }}
            />
          </div>

          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-foreground-2">
            <span>
              {status.done}/{status.total} documents
            </span>
            <span>cost so far ${status.cost_so_far.toFixed(2)}</span>
            {status.failed > 0 && (
              <span className="font-medium text-warning">
                {status.failed} failed
                {status.rate_limited > 0 ? ` (${status.rate_limited} throttled)` : ""} —
                infrastructure, not coverage gaps
              </span>
            )}
            {status.current && <span className="font-mono">{status.current}</span>}
          </div>

          {status.aborted_reason && (
            <div className="rounded-md border border-danger/30 bg-danger/5 px-3 py-2 text-xs text-danger">
              🛑 Aborted — too many consecutive{" "}
              {status.aborted_reason === "rate_limited" ? "throttled" : "failed"} documents
              {status.abort_error_type ? ` (${status.abort_error_type})` : ""}. The corpus was not
              fully analysed.{" "}
              {status.aborted_reason === "rate_limited" ? (
                <>
                  You&apos;re being throttled — <strong>lower</strong>{" "}
                  <span className="font-mono">AI_REQUESTS_PER_MINUTE_BEDROCK</span> (send fewer
                  requests to stay under Bedrock&apos;s limit), restart the backend, then resume. To
                  go faster instead, raise the AWS account&apos;s Bedrock quota.
                </>
              ) : (
                <>Fix credentials (AWS_PROFILE + `aws sso login`), then resume.</>
              )}
            </div>
          )}

          {status.finished && (
            <div className="space-y-2 text-xs text-muted-foreground">
              <p>
                Output written to <span className="font-mono">{status.output_dir}</span> —{" "}
                <span className="font-mono">_SUMMARY.md</span>,{" "}
                <span className="font-mono">_FINDINGS.csv</span>, and per-document JSON.
              </p>
              {status.done < status.total && (
                <button
                  type="button"
                  onClick={() => onStart(status.run_id)}
                  disabled={starting}
                  className="rounded-md bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
                >
                  {starting
                    ? "Resuming…"
                    : `Resume — ${status.total - status.done} documents remaining`}
                </button>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-2xl font-semibold text-foreground">{value}</div>
      <div className="text-xs uppercase tracking-wide text-muted-foreground">{label}</div>
    </div>
  );
}
