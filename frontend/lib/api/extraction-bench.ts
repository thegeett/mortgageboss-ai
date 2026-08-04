/**
 * Extraction-bench data layer (dev-only tool).
 *
 * Drives the dev-gated backend at /api/v1/dev/extraction-bench/* — which is ABSENT (404) in production
 * (mounted only when the backend is in development). This tool MEASURES coverage, not accuracy, and
 * persists nothing. See docs/tickets/extraction-bench.md.
 */
import { apiClient } from "@/lib/api/client";

const BASE = "/api/v1/dev/extraction-bench";

export interface BenchPreview {
  root: string;
  total: number;
  readable: number;
  by_extension: Record<string, number>;
  unreadable: { file: string; reason: string }[];
  per_doc_estimate: number;
  estimated_cost: number;
  provider: string;
  extraction_model: string;
  note: string;
}

export interface BenchStart {
  run_id: string;
  output_dir: string;
  to_run: number;
}

export interface BenchStatus {
  run_id: string;
  total: number;
  done: number;
  current: string | null;
  cost_so_far: number;
  cancelled: boolean;
  finished: boolean;
  output_dir: string;
}

export async function previewBench(root: string): Promise<BenchPreview> {
  const res = await apiClient.post<{ preview: BenchPreview }>(`${BASE}/preview`, { root });
  return res.data.preview;
}

export async function startBench(root: string): Promise<BenchStart> {
  const res = await apiClient.post<BenchStart>(`${BASE}/start`, { root });
  return res.data;
}

export async function benchStatus(runId: string): Promise<BenchStatus> {
  const res = await apiClient.get<BenchStatus>(`${BASE}/status/${runId}`);
  return res.data;
}

export async function cancelBench(runId: string): Promise<BenchStatus> {
  const res = await apiClient.post<BenchStatus>(`${BASE}/cancel/${runId}`);
  return res.data;
}
