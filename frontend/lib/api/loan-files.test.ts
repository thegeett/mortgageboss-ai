import { describe, expect, it, vi } from "vitest";

const get = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/client", () => ({ apiClient: { get } }));

import { fetchLoanFiles, loanFilesQueryKey } from "./loan-files";

describe("fetchLoanFiles — the assignee filter (LP-MB-Admin-05)", () => {
  it("sends assignee with the other filters", async () => {
    get.mockResolvedValue({ data: { items: [], total: 0, page: 1, page_size: 20 } });

    await fetchLoanFiles({ statuses: ["draft"], assignee: "me" });

    const url = get.mock.calls[0]?.[0] as string;
    const params = new URLSearchParams(url.split("?")[1]);
    expect(params.get("assignee")).toBe("me");
    expect(params.getAll("status")).toEqual(["draft"]);
  });

  it("sends nothing for anyone, and keys the cache by it", async () => {
    get.mockResolvedValue({ data: { items: [], total: 0, page: 1, page_size: 20 } });

    await fetchLoanFiles({ assignee: null });

    expect((get.mock.calls.at(-1)?.[0] as string).includes("assignee")).toBe(false);
    expect(loanFilesQueryKey({ assignee: "unassigned" })).not.toEqual(loanFilesQueryKey({}));
  });
});
