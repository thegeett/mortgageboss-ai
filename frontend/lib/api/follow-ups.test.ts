// @vitest-environment jsdom
/**
 * LP-1014 — what the follow-up requests actually send: the Send's `follow_up` body, the five
 * actions' paths and bodies, and what each refreshes.
 */
import { apiClient } from "@/lib/api/client";
import { makeQueryClient } from "@/lib/query-client";
import { QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { followUpsQueryKey, messageQueryKey, useSendDraft } from "./communications";
import { useFollowUpAction } from "./follow-ups";

vi.mock("@/lib/api/client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn() },
}));

const FILE = "LF-JR4T";
const post = vi.mocked(apiClient.post);
const patch = vi.mocked(apiClient.patch);
const FOLLOW_UP = { interval_days: 4, max_auto: 1, time: "09:30", tz: "America/Chicago" };

afterEach(() => vi.clearAllMocks());

function setup() {
  const client = makeQueryClient();
  const invalidate = vi.spyOn(client, "invalidateQueries");
  const wrapper = ({ children }: { children: React.ReactNode }) =>
    React.createElement(QueryClientProvider, { client }, children);
  return { wrapper, invalidate };
}

describe("the Send's follow-up", () => {
  it("posts follow_up with transmit, and refreshes the Follow-ups list", async () => {
    post.mockResolvedValue({ data: { id: "d1" } });
    const { wrapper, invalidate } = setup();
    const { result } = renderHook(() => useSendDraft(FILE), { wrapper });
    await act(() =>
      result.current.mutateAsync({
        draftId: "d1",
        recipient: "jane@example.test",
        body: "Hi",
        transmit: true,
        followUp: FOLLOW_UP,
      }),
    );
    expect(post.mock.calls[0]?.[1]).toMatchObject({ transmit: true, follow_up: FOLLOW_UP });
    expect(invalidate.mock.calls.map((c) => c[0]?.queryKey)).toContainEqual(
      followUpsQueryKey(FILE),
    );
  });

  it("never posts follow_up without transmit (Mark as sent)", async () => {
    post.mockResolvedValue({ data: { id: "d1" } });
    const { wrapper } = setup();
    const { result } = renderHook(() => useSendDraft(FILE), { wrapper });
    await act(() =>
      result.current.mutateAsync({
        draftId: "d1",
        recipient: "jane@example.test",
        body: "Hi",
        followUp: FOLLOW_UP,
      }),
    );
    expect(post.mock.calls[0]?.[1]).not.toHaveProperty("follow_up");
  });
});

describe("the five actions", () => {
  const BASE = `/api/v1/loan-files/${FILE}/messages/m1`;
  const SETTINGS = { interval_days: 5, max_auto: 3, time: "08:15" };

  it.each([
    [{ kind: "stop" as const }, "post", `${BASE}/follow-up/stop`, undefined],
    [{ kind: "resume" as const }, "post", `${BASE}/follow-up/resume`, undefined],
    [{ kind: "send-now" as const }, "post", `${BASE}/follow-up/send-now`, undefined],
    [
      { kind: "start" as const, settings: SETTINGS, tz: "America/Denver" },
      "post",
      `${BASE}/follow-up/start`,
      { ...SETTINGS, tz: "America/Denver" },
    ],
    [{ kind: "edit" as const, settings: SETTINGS }, "patch", `${BASE}/follow-up`, SETTINGS],
  ])("%o → %s %s", async (action, method, path, body) => {
    const call = method === "post" ? post : patch;
    call.mockResolvedValue({ data: {} });
    const { wrapper, invalidate } = setup();
    const { result } = renderHook(() => useFollowUpAction(FILE, "m1"), { wrapper });
    await act(() => result.current.mutateAsync(action));
    expect(call.mock.calls[0]?.[0]).toBe(path);
    expect(call.mock.calls[0]?.[1]).toEqual(body);
    const keys = invalidate.mock.calls.map((c) => c[0]?.queryKey);
    expect(keys).toContainEqual(followUpsQueryKey(FILE));
    expect(keys).toContainEqual(messageQueryKey(FILE, "m1"));
  });
});
