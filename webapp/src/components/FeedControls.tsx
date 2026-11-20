import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api, type CategoryId, type Sort, type Source } from "../lib/api";
import { t } from "../lib/i18n";
import { filters, useFilters } from "../lib/store";
import { haptic } from "../lib/telegram";
import { CATEGORIES } from "./Category";
import { CheckIcon, CloseIcon, SearchIcon, SlidersIcon } from "./Icons";

export function SearchBar() {
  const f = useFilters();
  const [value, setValue] = useState(f.q);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => setValue(f.q), [f.q]);
  useEffect(() => {
    if (value === f.q) return;
    const id = setTimeout(() => filters.set({ q: value, sort: value.trim() ? f.sort : f.sort === "relevance" ? "newest" : f.sort }), 350);
    return () => clearTimeout(id);
  }, [value, f.q, f.sort]);

  return (
    <form
      role="search"
      onSubmit={(e) => {
        e.preventDefault();
        filters.set({ q: value });
        inputRef.current?.blur(); // hides the mobile keyboard
      }}
      className="relative flex-1"
    >
      <SearchIcon size={18} className="pointer-events-none absolute top-1/2 left-3.5 -translate-y-1/2 text-faint" />
      <input
        ref={inputRef}
        type="search"
        inputMode="search"
        enterKeyHint="search"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder={t("searchPlaceholder")}
        maxLength={200}
        aria-label={t("searchPlaceholder")}
        className="h-11 w-full rounded-[14px] border border-line bg-surface pr-10 pl-10 text-[15px] text-text placeholder:text-faint focus:border-accent/60 focus:outline-none [&::-webkit-search-cancel-button]:hidden"
      />
      {value && (
        <button
          type="button"
          aria-label={t("clear")}
          onClick={() => {
            setValue("");
            filters.set({ q: "", sort: f.sort === "relevance" ? "newest" : f.sort });
          }}
          className="absolute top-1/2 right-1.5 grid h-8 w-8 -translate-y-1/2 place-items-center rounded-full text-faint hover:text-text"
        >
          <CloseIcon size={16} />
        </button>
      )}
    </form>
  );
}

export function CategoryChips() {
  const f = useFilters();
  const items: (CategoryId | null)[] = [null, ...CATEGORIES];
  return (
    <div className="-mx-4 flex gap-2 overflow-x-auto px-4 py-0.5 no-scrollbar" role="tablist" aria-label={t("categories")}>
      {items.map((c) => {
        const active = f.category === c;
        return (
          <button
            key={c ?? "all"}
            role="tab"
            type="button"
            aria-selected={active}
            onClick={() => {
              haptic.select();
              filters.set({ category: c });
              window.scrollTo({ top: 0 });
            }}
            className={`press h-9 shrink-0 rounded-full px-4 text-[14px] font-medium transition-colors ${
              active ? "bg-text text-bg" : "border border-line bg-surface text-muted hover:text-text"
            }`}
          >
            {c ? t(c) : t("all")}
          </button>
        );
      })}
    </div>
  );
}

export function FilterButton({ onClick }: { onClick: () => void }) {
  const f = useFilters();
  const n = f.sources.length + (f.sort !== "newest" ? 1 : 0);
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={t("filters")}
      className={`press relative grid h-11 w-11 shrink-0 place-items-center rounded-[14px] border transition-colors ${n ? "border-accent/50 bg-accent-soft text-accent-ink" : "border-line bg-surface text-muted"}`}
    >
      <SlidersIcon size={20} />
      {n > 0 && (
        <span className="absolute -top-1 -right-1 min-w-[18px] rounded-full bg-accent px-1 text-[10.5px] leading-[18px] font-bold text-white">
          {n}
        </span>
      )}
    </button>
  );
}

/** Active source filters shown as removable pills under the search bar. */
export function ActiveSourcePills({ sources }: { sources: Source[] }) {
  const f = useFilters();
  if (!f.sources.length) return null;
  const byId = new Map(sources.map((s) => [s.id, s]));
  return (
    <div className="-mx-4 flex gap-2 overflow-x-auto px-4 no-scrollbar">
      {f.sources.map((id) => (
        <button
          key={id}
          type="button"
          onClick={() => filters.set({ sources: f.sources.filter((x) => x !== id) })}
          className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full bg-accent-soft pr-2 pl-3 text-[13px] font-medium text-accent-ink"
        >
          {byId.get(id)?.name ?? id}
          <CloseIcon size={14} />
        </button>
      ))}
    </div>
  );
}

const SORTS: Sort[] = ["newest", "oldest", "relevance"];

export function FilterSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const f = useFilters();
  const [draft, setDraft] = useState({ sources: f.sources, sort: f.sort });
  const { data } = useQuery({ queryKey: ["sources"], queryFn: ({ signal }) => api.sources(signal), staleTime: 120_000 });

  useEffect(() => {
    if (open) setDraft({ sources: f.sources, sort: f.sort });
  }, [open, f.sources, f.sort]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [open, onClose]);

  if (!open) return null;
  const sources = (data?.data ?? []).filter((s) => s.enabled);
  const toggle = (id: string) =>
    setDraft((d) => ({ ...d, sources: d.sources.includes(id) ? d.sources.filter((x) => x !== id) : [...d.sources, id] }));

  // Portal to <body>: an animated/transformed ancestor would otherwise become the
  // containing block for this fixed overlay and push the sheet off-screen.
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-center" role="dialog" aria-modal="true" aria-label={t("filters")}>
      <button type="button" aria-label={t("clear")} onClick={onClose} className="fade-in absolute inset-0 bg-black/55" />
      <div className="sheet-enter relative flex max-h-[85dvh] w-full max-w-lg flex-col rounded-t-[26px] border border-line bg-bg pb-safe sm:rounded-[26px]">
        <div className="mx-auto mt-2.5 h-1 w-10 rounded-full bg-surface-3 sm:hidden" />
        <header className="flex items-center justify-between px-5 pt-3 pb-2">
          <h3 className="text-[18px] font-semibold tracking-[-0.01em]">{t("filters")}</h3>
          <button
            type="button"
            onClick={() => setDraft({ sources: [], sort: "newest" })}
            className="text-[14px] font-medium text-accent-ink"
          >
            {t("clear")}
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-5 pb-4">
          <div className="mt-2 grid grid-cols-3 gap-1 rounded-[14px] bg-surface p-1">
            {SORTS.map((s) => {
              const disabled = s === "relevance" && !f.q.trim();
              return (
                <button
                  key={s}
                  type="button"
                  disabled={disabled}
                  onClick={() => setDraft((d) => ({ ...d, sort: s }))}
                  className={`h-9 rounded-[10px] text-[13px] font-medium transition-colors disabled:opacity-35 ${draft.sort === s ? "bg-surface-3 text-text" : "text-muted"}`}
                >
                  {t(s)}
                </button>
              );
            })}
          </div>

          {CATEGORIES.map((cat) => {
            const list = sources.filter((s) => s.category === cat);
            if (!list.length) return null;
            return (
              <section key={cat} className="mt-5">
                <h4 className="mb-1.5 text-[11px] font-semibold tracking-[0.12em] uppercase" style={{ color: `var(--c-${cat})` }}>
                  {t(cat)}
                </h4>
                <ul className="overflow-hidden rounded-[16px] border border-line bg-surface">
                  {list.map((s) => {
                    const on = draft.sources.includes(s.id);
                    return (
                      <li key={s.id} className="border-b border-line last:border-0">
                        <button
                          type="button"
                          onClick={() => toggle(s.id)}
                          aria-pressed={on}
                          className="flex h-12 w-full items-center justify-between px-4 text-left text-[15px]"
                        >
                          <span>{s.name}</span>
                          <span
                            className={`grid h-6 w-6 place-items-center rounded-full border transition-colors ${on ? "border-accent bg-accent text-white" : "border-line"}`}
                          >
                            {on && <CheckIcon size={14} strokeWidth={2.6} />}
                          </span>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              </section>
            );
          })}
        </div>

        <div className="border-t border-line px-5 pt-3 pb-4">
          <button
            type="button"
            onClick={() => {
              filters.set(draft);
              haptic.success();
              onClose();
              window.scrollTo({ top: 0 });
            }}
            className="press h-12 w-full rounded-[14px] bg-accent text-[15.5px] font-semibold text-white"
          >
            {t("apply")}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
