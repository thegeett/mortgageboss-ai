// @vitest-environment jsdom
/**
 * The pipeline's borrower-name search never reaches the URL (LP-933, ADR-405 as amended).
 *
 * Asserted on the rendered `DashboardPage`, because the defect lived in the page's effect that wrote
 * the typed term into `router.replace`, not in a helper. Every URL the page asks the router for is
 * recorded, and every test checks the term is in none of them. That check is only worth something if
 * the recorder records, so the legacy-link test is the positive control: there the page MUST call
 * `router.replace`, and the test reads the call back.
 */
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// ONE router object, as Next gives: the page's effects list the router as a dependency, and a new
// object per render would re-run them and record calls the real app never makes.
const nav = vi.hoisted(() => {
  const state = { params: new URLSearchParams(), urls: [] as string[] };
  const router = {
    push: (url: string) => state.urls.push(url),
    replace: (url: string) => state.urls.push(url),
  };
  return Object.assign(state, { router });
});
vi.mock("next/navigation", () => ({
  useRouter: () => nav.router,
  useSearchParams: () => nav.params,
}));

/**
 * Every search the page asked the list endpoint for, in requests it enabled. The PAGE's request only:
 * `pageSize: 1` is the unfiltered count the empty state asks for, always with no search, and every
 * list here is empty, so it would otherwise interleave a "" after each real request.
 */
const requested = vi.hoisted(() => ({ searches: [] as string[] }));
vi.mock("@/lib/api/loan-files", () => ({
  useLoanFiles: (query: { search: string; pageSize: number }, options?: { enabled?: boolean }) => {
    if (options?.enabled !== false && query.pageSize !== 1) requested.searches.push(query.search);
    return {
      data: { items: [], total: 0, page: 1, page_size: 20 },
      isPending: false,
      isError: false,
    };
  },
}));

const views = vi.hoisted(() => ({ data: [] as unknown[] }));
vi.mock("@/lib/api/saved-views", () => ({
  useSavedViews: () => ({ data: views.data, isPending: false, isError: false }),
}));
vi.mock("@/components/file/delete-file-dialog", () => ({ DeleteFileDialog: () => null }));

import { useAuthStore } from "@/lib/stores/auth-store";
import {
  PIPELINE_SEARCH_STORAGE_KEY,
  usePipelineSearchStore,
} from "@/lib/stores/pipeline-search-store";
import DashboardPage from "./page";

const TERM = "Ellis";

beforeEach(() => {
  vi.useFakeTimers();
  // Signed in: the page does not trust a stored search until it knows who is signed in.
  useAuthStore.setState({ user: { id: "u1" } as never, accessToken: "t" });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
  nav.params = new URLSearchParams();
  nav.urls = [];
  requested.searches = [];
  views.data = [];
  useAuthStore.setState({ user: null, accessToken: null });
  window.sessionStorage.clear();
  usePipelineSearchStore.setState({ search: "", viewId: null, userId: null });
});

/** Render and let the store hydrate (a resolved promise) and effects settle. */
async function renderDashboard() {
  const result = render(<DashboardPage />);
  await act(async () => {
    await Promise.resolve();
  });
  return result;
}

async function type(value: string) {
  fireEvent.change(screen.getByRole("searchbox"), { target: { value } });
  await act(async () => {
    vi.advanceTimersByTime(300);
  });
}

/**
 * A refresh: the in-memory store starts empty again and sessionStorage does not. Resetting the store
 * writes through persist, so the saved entry is put back afterwards, as a reload would find it.
 */
function refresh(previous: { unmount: () => void }) {
  previous.unmount();
  const saved = window.sessionStorage.getItem(PIPELINE_SEARCH_STORAGE_KEY);
  usePipelineSearchStore.setState({ search: "", viewId: null, userId: null });
  if (saved !== null) window.sessionStorage.setItem(PIPELINE_SEARCH_STORAGE_KEY, saved);
}

/**
 * A full page reload: a new JS context, so the in-memory auth store starts signed out WITHOUT the
 * tab ever seeing a sign-out, and sessionStorage is all that carries over. Both stores are reset
 * (each writes through its subscribers), then the saved entry is put back as the reload finds it.
 */
function reload(previous: { unmount: () => void }) {
  previous.unmount();
  const saved = window.sessionStorage.getItem(PIPELINE_SEARCH_STORAGE_KEY);
  useAuthStore.setState({ user: null, accessToken: null });
  usePipelineSearchStore.setState({ search: "", viewId: null, userId: null });
  if (saved !== null) window.sessionStorage.setItem(PIPELINE_SEARCH_STORAGE_KEY, saved);
}

const searchBox = () => screen.getByRole("searchbox") as HTMLInputElement;
const stored = () => window.sessionStorage.getItem(PIPELINE_SEARCH_STORAGE_KEY) ?? "";

function expectTermInNoUrl() {
  for (const url of nav.urls) expect(url).not.toContain(TERM);
}

describe("the pipeline search stays out of the URL", () => {
  it("filters by what is typed without writing it to the URL", async () => {
    await renderDashboard();
    await type(TERM);

    expect(requested.searches.at(-1)).toBe(TERM);
    expectTermInNoUrl();
    // Kept for a refresh in this tab, in sessionStorage.
    expect(stored()).toContain(TERM);
  });

  it("keeps the search across a refresh in the same tab, still out of the URL", async () => {
    const first = await renderDashboard();
    await type(TERM);
    refresh(first);
    requested.searches = [];

    await renderDashboard();

    expect(searchBox().value).toBe(TERM);
    expect(requested.searches.at(-1)).toBe(TERM);
    // The request that ran before the stored term was read would have been the unsearched list.
    expect(requested.searches).not.toContain("");
    expectTermInNoUrl();
  });

  it("opens a link in a new tab with its filters and no search", async () => {
    // A new tab has its own, empty sessionStorage; the link is all it has.
    nav.params = new URLSearchParams("status=draft");
    await renderDashboard();

    expect(searchBox().value).toBe("");
    expect(requested.searches.at(-1)).toBe("");
  });

  it("applies a saved view's own search term without it reaching the URL", async () => {
    views.data = [
      { id: "v1", name: "Ellis files", filters: { statuses: ["draft"], search: TERM } },
    ];
    nav.params = new URLSearchParams("status=draft&view=v1");

    await renderDashboard();

    expect(searchBox().value).toBe(TERM);
    expect(requested.searches.at(-1)).toBe(TERM);
    expectTermInNoUrl();
  });

  it("keeps a term typed on top of a view across a refresh on that view", async () => {
    views.data = [{ id: "v1", name: "Drafts", filters: { statuses: ["draft"], search: null } }];
    nav.params = new URLSearchParams("status=draft&view=v1");
    const first = await renderDashboard();
    await type(TERM);
    refresh(first);

    await renderDashboard();

    expect(searchBox().value).toBe(TERM);
    expectTermInNoUrl();
  });

  it("strips a term from a link made before LP-933, and does not apply it", async () => {
    nav.params = new URLSearchParams(`status=draft&q=${TERM}`);

    await renderDashboard();

    // The positive control for every `expectTermInNoUrl` in this file: the router IS recorded.
    expect(nav.urls).toEqual(["/dashboard?status=draft"]);
    expect(searchBox().value).toBe("");
    expect(requested.searches).not.toContain(TERM);
  });

  it("clears the search with the other filters", async () => {
    await renderDashboard();
    await type(TERM);

    act(() => {
      fireEvent.click(screen.getByRole("button", { name: /clear the filters/i }));
    });

    expect(usePipelineSearchStore.getState().search).toBe("");
    expectTermInNoUrl();
  });

  it("still searches when sessionStorage refuses every access", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("denied", "SecurityError");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("denied", "QuotaExceededError");
    });

    await renderDashboard();
    await type(TERM);

    expect(requested.searches.at(-1)).toBe(TERM);
    expectTermInNoUrl();
  });

  it("forgets the search when the signed-in user signs out", async () => {
    await renderDashboard();
    await type(TERM);
    expect(usePipelineSearchStore.getState().search).toBe(TERM);

    act(() => {
      useAuthStore.getState().clearAuth();
    });

    expect(usePipelineSearchStore.getState().search).toBe("");
    expect(stored()).not.toContain(TERM);
  });

  it("does not hand one user's search to the next after a reload (LP-933 review)", async () => {
    // The sign-out this tab never saw: another tab, a session expiry, or a reload while signed
    // out. The in-memory auth store starts empty after a reload, so "someone -> no one" is never
    // observed here, and only the stamp on the stored term can tell whose it is.
    const first = await renderDashboard();
    await type(TERM);
    expect(stored()).toContain(TERM);
    reload(first);
    requested.searches = [];

    const second = render(<DashboardPage />);
    await act(async () => {
      await Promise.resolve();
    });
    // Not signed in yet: nothing may be requested with a term that could be someone else's.
    expect(requested.searches).not.toContain(TERM);

    act(() => {
      useAuthStore.setState({ user: { id: "u2" } as never, accessToken: "t2" });
    });
    await act(async () => {
      await Promise.resolve();
    });

    expect(searchBox().value).toBe("");
    expect(requested.searches).not.toContain(TERM);
    expect(stored()).not.toContain(TERM);
    second.unmount();
  });

  it("keeps the search across a reload when the same user signs back in", async () => {
    const first = await renderDashboard();
    await type(TERM);
    reload(first);

    render(<DashboardPage />);
    await act(async () => {
      await Promise.resolve();
    });
    act(() => {
      useAuthStore.setState({ user: { id: "u1" } as never, accessToken: "t" });
    });
    await act(async () => {
      await Promise.resolve();
    });

    expect(searchBox().value).toBe(TERM);
    expect(requested.searches.at(-1)).toBe(TERM);
  });
});
