import { describe, expect, it, vi } from "vitest";

const get = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/client", () => ({ apiClient: { get } }));

import { fetchCapabilities } from "./capabilities";

describe("fetchCapabilities", () => {
  it("asks the route the server actually mounts", async () => {
    // It asked for `/capabilities`, which 404'd on every deployment and read both switches as off
    // (LP-909 §5). The server mounts the router under `/api/v1`.
    get.mockResolvedValueOnce({ data: { receiving: true, polish: false } });

    const result = await fetchCapabilities();

    expect(get).toHaveBeenCalledWith("/api/v1/capabilities");
    expect(result).toEqual({ receiving: true, polish: false });
  });
});
