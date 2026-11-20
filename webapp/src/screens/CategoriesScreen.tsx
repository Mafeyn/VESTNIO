import { useQuery } from "@tanstack/react-query";
import { CategoryGlyph } from "../components/Category";
import { ChevronRight } from "../components/Icons";
import { ErrorView } from "../components/States";
import { api, type CategoryId } from "../lib/api";
import { relativeTime, t } from "../lib/i18n";
import { navigate } from "../lib/router";
import { filters } from "../lib/store";
import { haptic } from "../lib/telegram";
import { ScreenHeader } from "./ScreenHeader";

export function CategoriesScreen() {
  const q = useQuery({ queryKey: ["categories"], queryFn: ({ signal }) => api.categories(signal), staleTime: 60_000 });

  const open = (id: CategoryId) => {
    haptic.select();
    filters.set({ category: id, sources: [] });
    navigate("/", { replace: true });
  };

  return (
    <div className="screen-enter">
      <ScreenHeader title={t("categories")} />
      {q.isError ? (
        <ErrorView error={q.error} onRetry={() => q.refetch()} />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {q.isPending
            ? Array.from({ length: 3 }, (_, i) => <div key={i} className="skeleton h-[148px] rounded-[22px]" />)
            : q.data.data.map((c) => (
                <button
                  key={c.id}
                  type="button"
                  onClick={() => open(c.id)}
                  className="card press group relative flex h-[148px] flex-col overflow-hidden rounded-[22px] p-5 text-left"
                >
                  <div
                    className="pointer-events-none absolute -top-16 -right-16 h-48 w-48 rounded-full opacity-25 blur-2xl"
                    style={{ background: `var(--c-${c.id})` }}
                  />
                  <div className="flex items-center justify-between">
                    <span
                      className="grid h-11 w-11 place-items-center rounded-[14px]"
                      style={{ color: `var(--c-${c.id})`, background: `color-mix(in oklab, var(--c-${c.id}) 16%, transparent)` }}
                    >
                      <CategoryGlyph category={c.id} size={22} />
                    </span>
                    <ChevronRight size={20} className="text-faint transition-transform group-hover:translate-x-0.5" />
                  </div>
                  <h3 className="font-display mt-auto text-[21px] font-semibold tracking-[-0.015em]">{t(c.id)}</h3>
                  <p className="mt-1 text-[13px] text-muted tabular-nums">
                    {t("articlesToday", { n: c.last_24h })} · {t("sourcesCount", { n: c.source_count })}
                    {c.latest_published_at && <> · {relativeTime(c.latest_published_at)}</>}
                  </p>
                </button>
              ))}
        </div>
      )}
    </div>
  );
}
