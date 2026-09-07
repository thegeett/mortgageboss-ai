// @vitest-environment node
/**
 * The two redirects from LP-UI-011, pinned.
 *
 * Both are one-line pages, which is exactly the kind of file that gets "tidied
 * up" by someone who cannot see why it exists. A redirect that silently becomes
 * a 404 is invisible until a user follows an old bookmark.
 *
 * These CALL the pages rather than reading their source. The first version
 * asserted `readFileSync(...).toContain('redirect("/dashboard")')`, which passes
 * on the string appearing anywhere — a comment, a disabled branch, a
 * copy-pasted docstring — and could not distinguish a page that redirects from
 * one that merely mentions redirecting. `redirect()` is mocked because the real
 * one throws NEXT_REDIRECT by design; mocking it is the supported way to assert
 * on the destination, and the destination is the whole behaviour.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

const redirect = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({ redirect }));

import LoanFilesIndex from "@/app/(protected)/loan-files/page";
import RootPage from "@/app/page";

beforeEach(() => redirect.mockClear());

describe("LP-UI-011 redirects", () => {
  it("`/` redirects to the dashboard, not to /login", () => {
    // /login would duplicate the protected layout's judgement about who is
    // allowed in, and would bounce a signed-in user through a screen they do
    // not need. See ADR-390.
    RootPage();
    expect(redirect).toHaveBeenCalledTimes(1);
    expect(redirect).toHaveBeenCalledWith("/dashboard");
  });

  it("`/loan-files` redirects to the dashboard so old bookmarks still land", () => {
    LoanFilesIndex();
    expect(redirect).toHaveBeenCalledTimes(1);
    expect(redirect).toHaveBeenCalledWith("/dashboard");
  });

  it("the developer health page moved rather than being deleted", async () => {
    // The 199-line splash that used to BE `/` is still useful; LP-UI-011 moved
    // it beside /dev/extraction-bench rather than deleting it. Imported so the
    // assertion is that the route module exists and exports a page, not that
    // some string appears in some file.
    const page = await import("@/app/(protected)/dev/health/page");
    expect(typeof page.default).toBe("function");
  });

  it("neither page renders anything of its own", () => {
    // A redirect page that also returns markup is a page that flashes content
    // before it moves, and on a slow client renders it fully.
    expect(RootPage()).toBeUndefined();
    expect(LoanFilesIndex()).toBeUndefined();
  });
});
