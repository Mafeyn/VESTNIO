/** Tiny external stores: feed filters (session) and bookmarks (persistent, local only). */
import { useSyncExternalStore } from "react";
import type { Article, CategoryId, Sort } from "./api";

function createStore<T>(initial: T, persist?: { key: string; storage: () => Storage }) {
  let state = initial;
  if (persist) {
    try {
      const raw = persist.storage().getItem(persist.key);
      if (raw) state = { ...initial, ...JSON.parse(raw) };
    } catch {
      /* private mode / blocked storage: keep defaults */
    }
  }
  const listeners = new Set<() => void>();
  return {
    get: () => state,
    set(next: Partial<T> | ((s: T) => Partial<T>)) {
      const patch = typeof next === "function" ? next(state) : next;
      state = { ...state, ...patch };
      if (persist) {
        try {
          persist.storage().setItem(persist.key, JSON.stringify(state));
        } catch {
          /* quota / blocked: in-memory only */
        }
      }
      listeners.forEach((l) => l());
    },
    subscribe(cb: () => void) {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
  };
}

// ---------------------------------------------------------------- filters
export interface Filters {
  category: CategoryId | null;
  sources: string[];
  q: string;
  sort: Sort;
}

export const filters = createStore<Filters>(
  { category: null, sources: [], q: "", sort: "newest" },
  { key: "vestnio.filters.v1", storage: () => sessionStorage },
);

export function useFilters(): Filters {
  return useSyncExternalStore(filters.subscribe, filters.get);
}

// -------------------------------------------------------------- bookmarks
/** A saved article keeps a snapshot, so Saved works offline and after the article ages out. */
export interface Bookmark extends Article {
  saved_at: string;
}

const bookmarks = createStore<{ items: Bookmark[] }>(
  { items: [] },
  { key: "vestnio.bookmarks.v1", storage: () => localStorage },
);

export function useBookmarks(): Bookmark[] {
  return useSyncExternalStore(bookmarks.subscribe, () => bookmarks.get().items);
}

export function useIsSaved(id: number): boolean {
  return useSyncExternalStore(bookmarks.subscribe, () => bookmarks.get().items.some((b) => b.id === id));
}

export function toggleBookmark(article: Article): boolean {
  const items = bookmarks.get().items;
  if (items.some((b) => b.id === article.id)) {
    bookmarks.set({ items: items.filter((b) => b.id !== article.id) });
    return false;
  }
  bookmarks.set({ items: [{ ...article, saved_at: new Date().toISOString() }, ...items].slice(0, 500) });
  return true;
}

// cross-tab sync (desktop browsers / Telegram Desktop with several windows)
window.addEventListener("storage", (e) => {
  if (e.key === "vestnio.bookmarks.v1" && e.newValue) {
    try {
      bookmarks.set(JSON.parse(e.newValue));
    } catch {
      /* ignore */
    }
  }
});
