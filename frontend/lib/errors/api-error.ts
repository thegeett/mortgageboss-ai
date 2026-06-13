/**
 * Client-side error normalization (LP-46).
 *
 * Turns any thrown value — an axios error, a network failure, a stray Error —
 * into ONE predictable shape the UI can render and branch on. The backend
 * speaks a consistent envelope (`{ error: { type, message, details? } }`,
 * LP-46); this reads that, with a fallback to the legacy `{ detail }` shape and
 * a safe generic default. We never surface a raw status/stack to the user.
 */
import { isAxiosError } from "axios";

/** A field-level validation problem from the backend's 422 envelope. */
export interface FieldError {
  field: string;
  message: string;
}

export type ErrorKind = "network" | "auth" | "not_found" | "validation" | "server" | "unknown";

export interface NormalizedError {
  kind: ErrorKind;
  /** HTTP status, or null for a network/transport failure (no response). */
  status: number | null;
  /** A SAFE, human-readable message suitable for display. */
  message: string;
  /** Field errors for a validation failure (422), else undefined. */
  details?: FieldError[];
}

/** The backend error envelope (LP-46). */
interface ErrorEnvelope {
  error?: {
    type?: string;
    message?: string;
    details?: FieldError[];
  };
  /** Legacy FastAPI default, kept as a fallback. */
  detail?: string;
}

const GENERIC_MESSAGE = "Something went wrong. Please try again.";
const NETWORK_MESSAGE = "Couldn't connect — check your connection and try again.";

function kindForStatus(status: number): ErrorKind {
  if (status === 401 || status === 403) return "auth";
  if (status === 404) return "not_found";
  if (status === 422) return "validation";
  if (status >= 500) return "server";
  return "unknown";
}

/**
 * Normalize any thrown value into a {@link NormalizedError}. Safe to call on
 * anything; never throws.
 */
export function normalizeError(error: unknown): NormalizedError {
  if (isAxiosError(error)) {
    // No response → a transport/network/timeout failure.
    if (!error.response) {
      return { kind: "network", status: null, message: NETWORK_MESSAGE };
    }
    const { status, data } = error.response;
    const envelope = (data ?? {}) as ErrorEnvelope;
    const message = envelope.error?.message ?? envelope.detail ?? GENERIC_MESSAGE;
    return {
      kind: kindForStatus(status),
      status,
      message,
      details: envelope.error?.details,
    };
  }
  // A non-axios throw (e.g. a render bug) — keep it safe and generic.
  return { kind: "unknown", status: null, message: GENERIC_MESSAGE };
}

/** Convenience: just the safe, displayable message for any thrown value. */
export function getErrorMessage(error: unknown): string {
  return normalizeError(error).message;
}
