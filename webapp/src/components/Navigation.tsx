import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { api } from "../lib/api";
import { t, type Key } from "../lib/i18n";
import { navigate, rememberScroll, type Route } from "../lib/router";
import { filters, useBookmarks, useFilters } from "../lib/store";
import { haptic } from "../lib/telegram";
import { CATEGORIES, CategoryGlyph } from "./Category";
import { BookmarkIcon, FeedIcon, GridIcon, BrandMark, SourcesIcon } from "./Icons";

const TABS: { name: Route["name"]; path: string; label: Key; icon: (active: boolean) => ReactNode }[] = [
  { name: "feed", path: "/", label: "feed", icon: () => <FeedIcon /> },
  { name: "categories", path: "/categories", label: "categories", icon: () => <GridIcon /> },
  { name: "sources", path: "/sources", label: "sources", icon: () => <SourcesIcon /> },
  { name: "saved", path: "/saved", label: "saved", icon: (a) => <BookmarkIcon filled={a} /> },
];

function goTab(path: string, active: boolean) {
  if (active) {
    window.scrollTo({ top: 0, behavior: "smooth" }); // tapping the active tab scrolls to top
    return;
  }
  haptic.select();
  rememberScroll();
  navigate(path, { replace: true });
}

export function BottomNav({ route }: { route: Route }) {
  const saved = useBookmarks().length;
  return (
    <nav className="glass fixed inset-x-0 bottom-0 z-30 border-t border-line pb-safe lg:hidden" aria-label="Main">
      <ul className="mx-auto grid h-[58px] max-w-lg grid-cols-4">
        {TABS.map((tab) => {
          const active = route.name === tab.name;
          return (
            <li key={tab.name}>
              <button
                type="button"
                onClick={() => goTab(tab.path, active)}
                aria-current={active ? "page" : undefined}
                className={`relative flex h-full w-full flex-col items-center justify-center gap-[3px] text-[10.5px] font-medium tracking-[0.01em] transition-colors ${active ? "text-accent-ink" : "text-faint"}`}
              >
                {tab.icon(active)}
                <span>{t(tab.label)}</span>
                {tab.name === "saved" && saved > 0 && (
                  <span className="absolute top-1.5 left-[calc(50%+6px)] min-w-4 rounded-full bg-accent px-1 text-[9.5px] leading-4 font-bold text-white">
                    {saved > 99 ? "99+" : saved}
                  </span>
                )}
              </button>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

export function Brand() {
  return (
    <div className="flex items-center gap-2">
      <div className="grid h-8 w-8 place-items-center rounded-[10px] bg-accent text-white shadow-[0_6px_18px_-6px_var(--accent)]">
        <BrandMark size={20} />
      </div>
      <span className="font-display text-[19px] font-bold tracking-[0.14em]">VESTNIO</span>
    </div>
  );
}

/** Desktop: navigation + category shortcuts + optional source filter list. */
export function Sidebar({ route }: { route: Route }) {
  const f = useFilters();
  const sources = useQuery({ queryKey: ["sources"], queryFn: ({ signal }) => api.sources(signal), staleTime: 120_000 });
  const toggleSource = (id: string) => {
    filters.set((s) => ({ sources: s.sources.includes(id) ? s.sources.filter((x) => x !== id) : [...s.sources, id] }));
    if (route.name !== "feed") navigate("/", { replace: true });
  };
  return (
    <aside className="sticky top-0 hidden h-[var(--tg-vh,100dvh)] w-[264px] shrink-0 flex-col gap-7 overflow-y-auto border-r border-line px-5 pt-7 pb-8 no-scrollbar lg:flex">
      <Brand />
      <nav aria-label="Main">
        <ul className="flex flex-col gap-0.5">
          {TABS.map((tab) => {
            const active = route.name === tab.name;
            return (
              <li key={tab.name}>
                <button
                  type="button"
                  onClick={() => goTab(tab.path, active)}
                  aria-current={active ? "page" : undefined}
                  className={`flex h-10 w-full items-center gap-3 rounded-xl px-3 text-[14.5px] font-medium transition-colors ${active ? "bg-accent-soft text-accent-ink" : "text-muted hover:bg-surface hover:text-text"}`}
                >
                  {tab.icon(active)}
                  {t(tab.label)}
                </button>
              </li>
            );
          })}
        </ul>
      </nav>

      <section>
        <h4 className="mb-2 px-3 text-[11px] font-semibold tracking-[0.12em] text-faint uppercase">{t("categories")}</h4>
        <ul className="flex flex-col gap-0.5">
          {CATEGORIES.map((c) => {
            const active = f.category === c && route.name === "feed";
            return (
              <li key={c}>
                <button
                  type="button"
                  onClick={() => {
                    filters.set({ category: f.category === c ? null : c });
                    if (route.name !== "feed") navigate("/", { replace: true });
                  }}
                  className={`flex h-9 w-full items-center gap-3 rounded-xl px-3 text-[14px] transition-colors ${active ? "bg-surface text-text" : "text-muted hover:bg-surface hover:text-text"}`}
                >
                  <span style={{ color: `var(--c-${c})` }}>
                    <CategoryGlyph category={c} size={17} />
                  </span>
                  {t(c)}
                </button>
              </li>
            );
          })}
        </ul>
      </section>

      <section className="min-h-0">
        <div className="mb-2 flex items-center justify-between px-3">
          <h4 className="text-[11px] font-semibold tracking-[0.12em] text-faint uppercase">{t("sources")}</h4>
          {f.sources.length > 0 && (
            <button type="button" onClick={() => filters.set({ sources: [] })} className="text-[12px] text-accent-ink">
              {t("clear")}
            </button>
          )}
        </div>
        <ul className="flex flex-col gap-0.5">
          {(sources.data?.data ?? [])
            .filter((s) => s.enabled)
            .map((s) => {
              const on = f.sources.includes(s.id);
              return (
                <li key={s.id}>
                  <button
                    type="button"
                    onClick={() => toggleSource(s.id)}
                    aria-pressed={on}
                    className={`flex h-8 w-full items-center gap-2.5 rounded-lg px-3 text-[13.5px] transition-colors ${on ? "text-text" : "text-muted hover:text-text"}`}
                  >
                    <span
                      className={`grid h-4 w-4 place-items-center rounded-[5px] border transition-colors ${on ? "border-accent bg-accent" : "border-line bg-surface"}`}
                    >
                      {on && <span className="h-1.5 w-1.5 rounded-[2px] bg-white" />}
                    </span>
                    <span className="truncate">{s.name}</span>
                    <span className="ml-auto h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: `var(--c-${s.category})` }} />
                  </button>
                </li>
              );
            })}
        </ul>
      </section>
    </aside>
  );
}
