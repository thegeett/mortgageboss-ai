import { AxiosError, AxiosHeaders } from "axios";
import { describe, expect, it } from "vitest";
import { getErrorMessage, normalizeError } from "./api-error";

/** The fallback wording, asserted in one place so a copy change is one edit. */
const GENERIC = "The request didn't complete, and nothing was saved. Try again.";

/** Build an AxiosError carrying a given response (status + data), like the client sees. */
function axiosErrorWith(status: number, data: unknown): AxiosError {
  const err = new AxiosError("Request failed");
  err.response = {
    status,
    statusText: "",
    data,
    headers: {},
    config: { headers: new AxiosHeaders() },
  };
  return err;
}

/** An AxiosError with no response — a network/transport failure. */
function networkError(): AxiosError {
  return new AxiosError("Network Error", "ERR_NETWORK");
}

describe("normalizeError", () => {
  it("reads the LP-46 envelope (type, message, details)", () => {
    const result = normalizeError(
      axiosErrorWith(422, {
        error: {
          type: "validation_error",
          message: "Some fields need your attention.",
          details: [{ field: "document_type", message: "String should have at least 1 character" }],
        },
      }),
    );
    expect(result.kind).toBe("validation");
    expect(result.status).toBe(422);
    expect(result.message).toBe("Some fields need your attention.");
    expect(result.details).toEqual([
      { field: "document_type", message: "String should have at least 1 character" },
    ]);
  });

  it("maps 401/403 to the auth kind", () => {
    expect(normalizeError(axiosErrorWith(401, { error: { message: "x" } })).kind).toBe("auth");
    expect(normalizeError(axiosErrorWith(403, { error: { message: "x" } })).kind).toBe("auth");
  });

  it("maps 404 to not_found and 5xx to server", () => {
    expect(normalizeError(axiosErrorWith(404, {})).kind).toBe("not_found");
    expect(normalizeError(axiosErrorWith(500, {})).kind).toBe("server");
  });

  it("falls back to the legacy {detail} shape", () => {
    const result = normalizeError(axiosErrorWith(404, { detail: "Document not found" }));
    expect(result.message).toBe("Document not found");
  });

  it("treats a missing response as a network error", () => {
    const result = normalizeError(networkError());
    expect(result.kind).toBe("network");
    expect(result.status).toBeNull();
    expect(result.message).toMatch(/connect/i);
  });

  it("uses a safe generic message when the body has none", () => {
    const result = normalizeError(axiosErrorWith(500, {}));
    expect(result.message).toBe(GENERIC);
  });

  it("never throws on a non-axios value", () => {
    const result = normalizeError(new Error("render bug: /internal/path"));
    expect(result.kind).toBe("unknown");
    expect(result.status).toBeNull();
    // Safe generic — never the raw internal text.
    expect(result.message).toBe(GENERIC);
    expect(result.message).not.toContain("/internal/path");
  });
});

describe("isGeneric — did the server actually say anything? (LP-UI-034)", () => {
  /**
   * Two call sites replace the fallback with something better ("The upload didn't
   * complete", "This file couldn't be read as a MISMO file"). Both used to decide
   * by comparing against the fallback's WORDING, which this ticket changed. The
   * flag is what they branch on now, so getting it backwards means either always
   * overriding a real server message, or never replacing the blank.
   */
  it("is false when the server sent a message", () => {
    const result = normalizeError(axiosErrorWith(422, { error: { message: "Not a MISMO file." } }));
    expect(result.isGeneric).toBe(false);
    expect(result.message).toBe("Not a MISMO file.");
  });

  it("is false for the legacy `detail` shape too", () => {
    const result = normalizeError(axiosErrorWith(400, { detail: "Bad request." }));
    expect(result.isGeneric).toBe(false);
  });

  it("is true when the body carried nothing usable", () => {
    expect(normalizeError(axiosErrorWith(500, {})).isGeneric).toBe(true);
  });

  it("is true for a non-axios throw", () => {
    expect(normalizeError(new Error("render bug")).isGeneric).toBe(true);
  });

  it("is false for a network failure, which has its own real message", () => {
    // A caller must not overwrite "Couldn't connect" with an upload-specific
    // guess: the connection is the finding, and it is more useful than the guess.
    const offline = normalizeError(Object.assign(new Error("net"), { isAxiosError: true }));
    expect(offline.kind).toBe("network");
    expect(offline.isGeneric).toBe(false);
  });
});

describe("getErrorMessage", () => {
  it("returns just the safe message", () => {
    expect(getErrorMessage(axiosErrorWith(404, { error: { message: "Not found" } }))).toBe(
      "Not found",
    );
    expect(getErrorMessage("a bare string")).toBe(GENERIC);
  });
});
