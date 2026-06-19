import { beforeEach, describe, expect, it, vi } from "vitest";

const post = vi.hoisted(() => vi.fn());
const get = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/client", () => ({ apiClient: { post, get } }));

import { fetchStatedFinancials, importMismo, statedFinancialsQueryKey } from "./mismo";

beforeEach(() => {
  post.mockReset();
  get.mockReset();
});

describe("importMismo", () => {
  it("posts the file as multipart to the import endpoint and returns the result", async () => {
    post.mockResolvedValue({
      data: { loan_file: { id: "lf1", display_id: "LF-1" }, warnings: [] },
    });
    const file = new File([new Uint8Array([1, 2, 3])], "app.xml", { type: "application/xml" });

    const result = await importMismo(file);

    expect(post).toHaveBeenCalledTimes(1);
    const call = post.mock.calls.at(0);
    if (!call) throw new Error("apiClient.post was not called");
    const [url, body, config] = call;
    expect(url).toBe("/api/v1/loan-files/import-mismo");
    expect(body).toBeInstanceOf(FormData);
    expect((body as FormData).get("file")).toBeInstanceOf(File);
    expect(config.headers["Content-Type"]).toBe("multipart/form-data");
    expect(result.loan_file.display_id).toBe("LF-1");
    expect(result.warnings).toEqual([]);
  });

  it("passes through parse warnings from a partial import", async () => {
    post.mockResolvedValue({
      data: { loan_file: { id: "lf1", display_id: "LF-1" }, warnings: ["Missing X"] },
    });
    const result = await importMismo(new File(["x"], "a.xml"));
    expect(result.warnings).toEqual(["Missing X"]);
  });
});

describe("fetchStatedFinancials", () => {
  it("reads the file's stated financials", async () => {
    get.mockResolvedValue({ data: { borrowers: [], liabilities: [], assets: [] } });
    await fetchStatedFinancials("LF-1");
    expect(get).toHaveBeenCalledWith("/api/v1/loan-files/LF-1/stated-financials");
  });

  it("builds a stable query key", () => {
    expect(statedFinancialsQueryKey("LF-1")).toEqual(["stated-financials", "LF-1"]);
  });
});
