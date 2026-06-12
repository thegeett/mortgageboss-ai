import { AxiosError, AxiosHeaders } from "axios";
import { describe, expect, it } from "vitest";
import { getErrorMessage, normalizeError } from "./api-error";

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
    expect(result.message).toBe("Something went wrong. Please try again.");
  });

  it("never throws on a non-axios value", () => {
    const result = normalizeError(new Error("render bug: /internal/path"));
    expect(result.kind).toBe("unknown");
    expect(result.status).toBeNull();
    // Safe generic — never the raw internal text.
    expect(result.message).toBe("Something went wrong. Please try again.");
    expect(result.message).not.toContain("/internal/path");
  });
});

describe("getErrorMessage", () => {
  it("returns just the safe message", () => {
    expect(getErrorMessage(axiosErrorWith(404, { error: { message: "Not found" } }))).toBe(
      "Not found",
    );
    expect(getErrorMessage("a bare string")).toBe("Something went wrong. Please try again.");
  });
});
