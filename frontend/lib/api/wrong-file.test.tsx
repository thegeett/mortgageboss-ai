// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { AxiosError, type AxiosResponse } from "axios";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

const post = vi.hoisted(() => vi.fn());
const get = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/client", () => ({ apiClient: { post, get } }));

import { useAttachPdf, useImportRound, useWrongFile, wrongFileQueryKey } from "./conditions";
import { useForwardAttachmentAsSheet } from "./inbound";
import { isWrongFileRefusal, withWrongFileConfirmation } from "./wrong-file";

function refusal(code: string, status = 409): AxiosError {
  const data = { error: { message: "This PDF does not look like this file's.", data: { code } } };
  return new AxiosError("refused", "ERR_BAD_REQUEST", undefined, undefined, {
    status,
    data,
  } as AxiosResponse);
}

function wrapper(client: QueryClient) {
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
}

afterEach(() => {
  vi.restoreAllMocks();
  post.mockReset();
});

describe("LP-951 review — the wrong-file refusal on the attach doors", () => {
  it("is told apart from any other 409 by its code", () => {
    expect(isWrongFileRefusal(refusal("wrong_file"))).toBe(true);
    expect(isWrongFileRefusal(refusal("other"))).toBe(false);
    expect(isWrongFileRefusal(refusal("wrong_file", 422))).toBe(false);
    expect(isWrongFileRefusal(new Error("x"))).toBe(false);
  });

  it("asks her, and resends with the confirmation only when she says yes", async () => {
    const ask = vi.spyOn(window, "confirm").mockReturnValue(true);
    const send = vi.fn().mockRejectedValueOnce(refusal("wrong_file")).mockResolvedValueOnce("ok");
    await expect(withWrongFileConfirmation(send)).resolves.toBe("ok");
    expect(ask).toHaveBeenCalledWith(expect.stringContaining("does not look like this file"));
    expect(send.mock.calls).toEqual([[false], [true]]);
  });

  it("cancelling rethrows the refusal and sends nothing more", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    const send = vi.fn().mockRejectedValue(refusal("wrong_file"));
    await expect(withWrongFileConfirmation(send)).rejects.toBeInstanceOf(AxiosError);
    expect(send).toHaveBeenCalledTimes(1);
  });

  it("another refusal never asks", async () => {
    const ask = vi.spyOn(window, "confirm");
    const send = vi.fn().mockRejectedValue(refusal("other"));
    await expect(withWrongFileConfirmation(send)).rejects.toBeInstanceOf(AxiosError);
    expect(ask).not.toHaveBeenCalled();
  });

  it("the attach-PDF hook sends the confirmation as a form field", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    post.mockRejectedValueOnce(refusal("wrong_file")).mockResolvedValueOnce({
      data: { round_id: "r1" },
    });
    const qc = new QueryClient();
    const { result } = renderHook(() => useAttachPdf("f1"), { wrapper: wrapper(qc) });
    result.current.mutate({ roundId: "r1", file: new File(["%PDF"], "s.pdf") });
    await waitFor(() => expect(post).toHaveBeenCalledTimes(2));
    expect((post.mock.calls[0]?.[1] as FormData).get("confirm_wrong_file")).toBeNull();
    expect((post.mock.calls[1]?.[1] as FormData).get("confirm_wrong_file")).toBe("true");
  });

  it("the forward-into-a-round hook sends it in the body; opening a new round never asks", async () => {
    const ask = vi.spyOn(window, "confirm").mockReturnValue(true);
    post.mockRejectedValueOnce(refusal("wrong_file")).mockResolvedValue({ data: {} });
    const qc = new QueryClient();
    const { result } = renderHook(() => useForwardAttachmentAsSheet("f1"), {
      wrapper: wrapper(qc),
    });
    result.current.mutate({ attachmentId: "a1", attachToRoundId: "r1" });
    await waitFor(() => expect(post).toHaveBeenCalledTimes(2));
    expect(post.mock.calls[0]?.[1]).toEqual({ attach_to_round_id: "r1" });
    expect(post.mock.calls[1]?.[1]).toEqual({ attach_to_round_id: "r1", confirm_wrong_file: true });

    post.mockReset();
    ask.mockClear();
    post.mockRejectedValueOnce(refusal("wrong_file"));
    result.current.mutate({ attachmentId: "a2", attachToRoundId: null });
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    expect(ask).not.toHaveBeenCalled();
  });

  it("a failed import refetches the round's wrong-file answer, so the warning can appear", async () => {
    post.mockRejectedValueOnce(refusal("wrong_file"));
    const qc = new QueryClient();
    const spy = vi.spyOn(qc, "invalidateQueries");
    const { result } = renderHook(() => useImportRound("f1"), { wrapper: wrapper(qc) });
    result.current.mutate("r1");
    await waitFor(() => expect(spy).toHaveBeenCalledWith({ queryKey: wrongFileQueryKey("r1") }));
  });

  it("the review screen asks again each time it opens, never from a minute-old answer", async () => {
    get.mockResolvedValue({ data: null });
    const qc = new QueryClient();
    const first = renderHook(() => useWrongFile("r1"), { wrapper: wrapper(qc) });
    await waitFor(() => expect(first.result.current.isSuccess).toBe(true));
    first.unmount();
    renderHook(() => useWrongFile("r1"), { wrapper: wrapper(qc) });
    await waitFor(() => expect(get).toHaveBeenCalledTimes(2));
  });
});
