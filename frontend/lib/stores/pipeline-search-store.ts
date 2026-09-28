/**
 * The pipeline's borrower-name search, kept OUT of the URL (LP-933, ADR-405 as amended).
 *
 * The search matches borrower NAMES, so writing it into `?q=` put a borrower's name into every copied
 * link, the recipient's clipboard and browser history. Every other pipeline filter (statuses, the
 * selected view) is a category and stays in the URL; this one lives here.
 *
 * SESSIONSTORAGE, NEVER LOCALSTORAGE. The term survives a refresh in the same tab, which is what a
 * processor expects of a search box, and dies with the tab. localStorage would keep a borrower's name
 * on the machine indefinitely and share it across every tab. A link pasted into a new tab starts with
 * no search, which is the point.
 *
 * EVERY STORAGE ACCESS IS IN A TRY/CATCH. sessionStorage throws in some private modes, when storage is
 * disabled, and on quota; a search box must keep working in memory when it does.
 *
 * `skipHydration`, rehydrated by the dashboard on mount. The server renders an empty search; reading
 * sessionStorage while the store is created would give the first client render a different value and
 * a hydration mismatch.
 *
 * `viewId` is the saved view the current search belongs to. Opening a view applies that view's own
 * search term from the server's copy of the view, never from the URL; a refresh on the same view keeps
 * whatever was typed on top of it. See `useApplyViewSearch` in the dashboard.
 *
 * CLEARED WHEN THE SIGNED-IN USER GOES AWAY OR CHANGES. The tab outlives a sign-out, so without this the
 * next person to sign in there would open the pipeline already searching the last person's borrower.
 */
import { useAuthStore } from "@/lib/stores/auth-store";
import { create } from "zustand";
import { type StateStorage, createJSONStorage, persist } from "zustand/middleware";

export const PIPELINE_SEARCH_STORAGE_KEY = "mbai.pipeline-search";

const tabStorage: StateStorage = {
  getItem: (name) => {
    try {
      return window.sessionStorage.getItem(name);
    } catch {
      return null;
    }
  },
  setItem: (name, value) => {
    try {
      window.sessionStorage.setItem(name, value);
    } catch {
      // Storage refused: the search still works for this page, it just will not survive a refresh.
    }
  },
  removeItem: (name) => {
    try {
      window.sessionStorage.removeItem(name);
    } catch {
      // As above.
    }
  },
};

interface PipelineSearchState {
  /** The committed search term (debounced), as sent to the list endpoint. */
  search: string;
  /** The saved view `search` was applied under; `null` for "All files". */
  viewId: string | null;
  setSearch: (search: string) => void;
  /** Select a view (or "All files", `null`) and the search that comes with it. */
  applyView: (viewId: string | null, search: string) => void;
  clear: () => void;
}

export const usePipelineSearchStore = create<PipelineSearchState>()(
  persist(
    (set) => ({
      search: "",
      viewId: null,
      setSearch: (search) => set({ search }),
      applyView: (viewId, search) => set({ viewId, search }),
      clear: () => set({ search: "", viewId: null }),
    }),
    {
      name: PIPELINE_SEARCH_STORAGE_KEY,
      storage: createJSONStorage(() => tabStorage),
      partialize: ({ search, viewId }) => ({ search, viewId }),
      skipHydration: true,
    },
  ),
);

useAuthStore.subscribe((state, previous) => {
  if (previous.user !== null && state.user?.id !== previous.user.id) {
    usePipelineSearchStore.getState().clear();
  }
});
