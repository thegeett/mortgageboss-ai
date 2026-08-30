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
  /**
   * True when `message` is the fallback rather than something the server said
   * (LP-UI-034).
   *
   * A caller that can say something better — "Upload failed", "Couldn't sign you
   * in" — needs to know whether it is overriding a real server message or filling
   * a blank. Two call sites were answering that by COMPARING against the
   * fallback string, which stops working the moment the wording changes, and this
   * ticket changes the wording.
   */
  isGeneric: boolean;
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

/**
 * What we say when the server told us nothing usable.
 *
 * NOT "something went wrong": that is an apology in place of information, and
 * LP-UI-034 bans it by name. This says what is known (the request failed), what
 * is not (why), and what is safe to assume (nothing was saved) — which is a
 * processor's actual next question after any failure on a file they are editing.
 *
 * A caller with something more specific should say that instead and can tell it
 * is overriding a blank via `isGeneric`.
 */
const GENERIC_MESSAGE = "The request didn't complete, and nothing was saved. Try again.";
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
      return { kind: "network", status: null, message: NETWORK_MESSAGE, isGeneric: false };
    }
    const { status, data } = error.response;
    const envelope = (data ?? {}) as ErrorEnvelope;
    const served = envelope.error?.message ?? envelope.detail;
    return {
      kind: kindForStatus(status),
      status,
      message: served ?? GENERIC_MESSAGE,
      details: envelope.error?.details,
      isGeneric: served == null,
    };
  }
  // A non-axios throw (e.g. a render bug) — keep it safe and generic.
  return { kind: "unknown", status: null, message: GENERIC_MESSAGE, isGeneric: true };
}

/** Convenience: just the safe, displayable message for any thrown value. */
export function getErrorMessage(error: unknown): string {
  return normalizeError(error).message;
}
