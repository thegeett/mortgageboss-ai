// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

const server = vi.hoisted(() => ({
  density: "compact" as string,
  put: vi.fn(),
  /** Held open by the in-flight-write test so the PUT does not resolve. */
  gate: undefined as Promise<void> | undefined,
}));

// Mocked at the TRANSPORT, not at the module's own exports: `usePreferences`
// and `useUpdatePreferences` call `fetchPreferences`/`updatePreferences` through
// module-internal references, so replacing those exports changes nothing the
// hooks actually reach. This way the real hooks run.
vi.mock("@/lib/api/client", () => ({
  apiClient: {
    get: async () => ({
      data: { default_aggression_level: "balanced", density: server.density },
    }),
    put: async (_url: string, body: unknown) => {
      server.put(body);
      if (server.gate) await server.gate;
      return { data: { default_aggression_level: "balanced", ...(body as object) } };
    },
  },
}));

import { DENSITY_COOKIE } from "@/lib/api/preferences";
import { useDensity } from "./use-density";

function cookieValue(): string | null {
  const found = document.cookie.split("; ").find((c) => c.startsWith(`${DENSITY_COOKIE}=`));
  return found ? (found.split("=")[1] ?? "") : null;
}

function render(options: { withPreferences?: boolean } = {}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, enabled: options.withPreferences ?? false } },
  });
  return {
    client,
    ...renderHook(() => useDensity(), {
      wrapper: ({ children }) => React.createElement(QueryClientProvider, { client }, children),
    }),
  };
}

afterEach(() => {
  cleanup();
  document.documentElement.removeAttribute("data-density");
  document.cookie = `${DENSITY_COOKIE}=;path=/;max-age=0`;
  server.density = "compact";
  server.put.mockReset();
  server.gate = undefined;
});

describe("useDensity", () => {
  it("adopts what the server stamped, without rewriting it", () => {
    document.documentElement.dataset.density = "relaxed";
    const { result } = render();
    expect(result.current.density).toBe("relaxed");
    expect(cookieValue()).toBeNull(); // adopting is not a write
  });

  it("writes the attribute and the cookie when you choose", async () => {
    const { result } = render();
    act(() => result.current.choose("comfortable"));
    expect(document.documentElement.dataset.density).toBe("comfortable");
    expect(cookieValue()).toBe("comfortable");
    await waitFor(() => expect(server.put).toHaveBeenCalledWith({ density: "comfortable" }));
  });

  it("DELETES the cookie for compact, the default the server tests against", async () => {
    document.documentElement.dataset.density = "relaxed";
    document.cookie = `${DENSITY_COOKIE}=relaxed;path=/`;
    const { result } = render();
    act(() => result.current.choose("compact"));
    expect(document.documentElement.dataset.density).toBeUndefined();
    expect(cookieValue()).toBeNull();
  });

  it("does not PUT when you re-pick the density you are already on", async () => {
    const { result } = render();

    // A positive control first, and AWAITED. Asserting "not called" straight
    // after `choose` passes whether or not the guard exists, because the
    // mutation's request happens a microtask later — which is exactly how the
    // first version of this test passed with the guard deleted.
    act(() => result.current.choose("relaxed"));
    await waitFor(() => expect(server.put).toHaveBeenCalledTimes(1));

    act(() => result.current.choose("relaxed"));
    await Promise.resolve();
    expect(server.put).toHaveBeenCalledTimes(1);
  });

  it("snaps back when the write fails, rather than lying until the next reload", async () => {
    // The DOM changes optimistically, so a failed PUT leaves the screen claiming
    // a preference the database does not hold — it "worked", then silently
    // reverted on some later load when the reconcile pulled the server's answer.
    server.put.mockImplementationOnce(() => {
      throw new Error("network");
    });
    const { result } = render();

    act(() => result.current.choose("relaxed"));
    expect(document.documentElement.dataset.density).toBe("relaxed");

    await waitFor(() => expect(result.current.density).toBe("compact"));
    expect(document.documentElement.dataset.density).toBeUndefined();
    expect(cookieValue()).toBeNull();
  });

  it("does not revert your choice while the write that makes it true is in flight", async () => {
    // The reconcile effect reads the server's answer, which is still the OLD one
    // until the PUT lands. Firing during the write snaps the whole UI back to the
    // previous density and then forward again — and the effect re-runs the moment
    // the mutation starts, so this is the common path, not a narrow race.
    server.density = "compact";
    const { result } = render({ withPreferences: true });
    await waitFor(() => expect(result.current.density).toBe("compact"));

    let release: (() => void) | undefined;
    server.gate = new Promise<void>((resolve) => {
      release = resolve;
    });

    act(() => result.current.choose("relaxed"));
    await act(async () => {
      await Promise.resolve();
    });

    expect(document.documentElement.dataset.density).toBe("relaxed");
    expect(result.current.density).toBe("relaxed");
    release?.();
  });

  it("reconciles a stale cookie to the server's answer (the other-device case)", async () => {
    document.documentElement.dataset.density = "compact";
    server.density = "relaxed";
    const { result } = render({ withPreferences: true });

    await waitFor(() => expect(result.current.density).toBe("relaxed"));
    expect(document.documentElement.dataset.density).toBe("relaxed");
    expect(cookieValue()).toBe("relaxed");
  });

  it("reconciles DOWN to compact too, where the attribute is absent rather than set", async () => {
    document.documentElement.dataset.density = "relaxed";
    server.density = "compact";
    const { result } = render({ withPreferences: true });

    await waitFor(() => expect(result.current.density).toBe("compact"));
    expect(document.documentElement.dataset.density).toBeUndefined();
  });
});
