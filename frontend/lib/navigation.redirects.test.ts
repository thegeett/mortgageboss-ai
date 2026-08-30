/**
 * The two redirects from LP-UI-011, pinned.
 *
 * Both are one-line pages, which is exactly the kind of file that gets
 * "tidied up" by someone who cannot see why it exists. A redirect that silently
 * becomes a 404 is invisible until a user follows an old bookmark.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const read = (p: string) => readFileSync(join(process.cwd(), p), "utf8");

describe("LP-UI-011 redirects", () => {
  it("`/` redirects to the dashboard, not to /login", () => {
    // /login would duplicate the protected layout's judgement about who is
    // allowed in, and would bounce a signed-in user through a screen they do
    // not need. See ADR-390.
    const source = read("app/page.tsx");
    expect(source).toContain('redirect("/dashboard")');
    expect(source).not.toContain('redirect("/login")');
  });

  it("`/loan-files` redirects to the dashboard so old bookmarks still land", () => {
    expect(read("app/(protected)/loan-files/page.tsx")).toContain('redirect("/dashboard")');
  });

  it("the developer health page moved rather than being deleted", () => {
    const health = read("app/(protected)/dev/health/page.tsx");
    expect(health).toContain("checkBackendHealth");
  });
});
