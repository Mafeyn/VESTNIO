/**
 * Minimal history router (no dependency) with per-entry scroll restoration.
 * Routes: /  /categories  /sources  /saved  /article/:id
 */
import { useSyncExternalStore } from "react";

export type Route =
  | { name: "feed" }
  | { name: "categories" }
  | { name: "sources" }
  | { name: "saved" }
  | { name: "article"; id: number };

const listeners = new Set<() => void>();
let current = parse(location.pathname);
let depth = (history.state?.depth as number | undefined) ?? 0;
const scrollByKey = new Map<string, number>();

if (history.state?.key === undefined) {
  history.replaceState({ key: "root", depth: 0 }, "");
}
if ("scrollRestoration" in history) history.scrollRestoration = "manual";

function parse(path: string): Route {
  const m = path.match(/^\/article\/(\d+)\/?$/);
  if (m) return { name: "article", id: Number(m[1]) };
  if (path.startsWith("/categories")) return { name: "categories" };
  if (path.startsWith("/sources")) return { name: "sources" };
  if (path.startsWith("/saved")) return { name: "saved" };
  return { name: "feed" };
}

function emit() {
  listeners.forEach((l) => l());
}

function saveScroll() {
  // keyed by history entry (exact back/forward restore) and by path (tab switches)
  scrollByKey.set(history.state?.key ?? "root", window.scrollY);
  scrollByKey.set(`path:${location.pathname}`, window.scrollY);
}

window.addEventListener("popstate", (e) => {
  current = parse(location.pathname);
  depth = (e.state?.depth as number | undefined) ?? 0;
  emit();
});

export function navigate(path: string, opts: { replace?: boolean } = {}) {
  saveScroll();
  const key = Math.random().toString(36).slice(2);
  if (opts.replace) {
    history.replaceState({ key, depth }, "", path);
  } else {
    depth += 1;
    history.pushState({ key, depth }, "", path);
  }
  current = parse(path);
  emit();
  window.scrollTo(0, 0);
}

/** Go back inside the app; if there is no in-app history, go to the feed. */
export function back() {
  if (depth > 0) {
    saveScroll();
    history.back();
  } else {
    navigate("/", { replace: true });
  }
}

export function canGoBack() {
  return depth > 0;
}

export function useRoute(): Route {
  return useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    () => current,
  );
}

/** Call after a screen's content has rendered to restore its previous scroll offset. */
export function restoreScroll() {
  const y = scrollByKey.get(history.state?.key ?? "root") ?? scrollByKey.get(`path:${location.pathname}`);
  if (y !== undefined) window.scrollTo(0, y);
}

/** Store scroll continuously so tab switches (replace navigation) also restore. */
export function rememberScroll() {
  saveScroll();
}
