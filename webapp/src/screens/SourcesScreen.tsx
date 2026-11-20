import { useQuery } from "@tanstack/react-query";
import { CATEGORIES } from "../components/Category";
import { ChevronRight } from "../components/Icons";
import { ErrorView } from "../components/States";
import { api, type Source } from "../lib/api";
import { relativeTime, t } from "../lib/i18n";
import { navigate } from "../lib/router";
import { filters } from "../lib/store";
import { haptic } from "../lib/telegram";
import { ScreenHeader } from "./ScreenHeader";

const STATUS_COLOR: Record<Source["status"], string> = {
  healthy: "var(--ok)",
  degraded: "var(--warn)",
  failing: "var(--bad)",
  pending: "var(--faint)",
  disabled: "var(--faint)",
};

export function SourcesScreen() {
  const q = useQuery({
    queryKey: ["sources"],
    queryFn: ({ signal }) => api.sources(signal),
    staleTime: 60_000,
    refetchInterval: 60_000,
  });

  const open = (s: Source) => {
    haptic.select();
    filters.set({ sources: [s.id], category: null, q: "" });
    navigate("/", { replace: true });
  };

  return (
    <div className="screen-enter">
      <ScreenHeader title={t("sources")} />
      {q.isError ? (
        <ErrorView error={q.error} onRetry={() => q.refetch()} />
      ) : q.isPending ? (
        <div className="flex flex-col gap-3">
          {Array.from({ length: 3 }, (_, i) => (
            <div key={i} className="skeleton h-[180px] rounded-[20px]" />
          ))}
        </div>
      ) : (
        <div className="grid gap-6 xl:grid-cols-2">
          {CATEGORIES.map((cat) => {
            const list = q.data.data.filter((s) => s.category === cat && s.enabled);
            if (!list.length) return null;
            return (
              <section key={cat}>
                <h2 className="mb-2 px-1 text-[12px] font-semibold tracking-[0.12em] uppercase" style={{ color: `var(--c-${cat})` }}>
                  {t(cat)}
                </h2>
                <ul className="card overflow-hidden rounded-[20px]">
                  {list.map((s) => (
                    <li key={s.id} className="border-b border-line last:border-0">
                      <button type="button" onClick={() => open(s)} className="flex w-full items-center gap-3.5 px-4 py-3.5 text-left transition-colors hover:bg-surface-2">
                        <span
                          className="grid h-10 w-10 shrink-0 place-items-center rounded-[12px] text-[15px] font-bold"
                          style={{ color: `var(--c-${cat})`, background: `color-mix(in oklab, var(--c-${cat}) 14%, transparent)` }}
                        >
                          {s.name.replace(/^The /, "").slice(0, 1)}
                        </span>
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            <span className="truncate text-[15.5px] font-semibold">{s.name}</span>
                            <span
                              className={`shrink-0 rounded-md px-1.5 py-0.5 text-[10px] font-semibold tracking-[0.06em] uppercase ${s.method === "telegram" ? "bg-[#2AABEE]/15 text-[#2AABEE]" : "bg-surface-2 text-faint"}`}
                            >
                              {s.method === "telegram" ? "TG" : s.method}
                            </span>
                          </div>
                          <div className="mt-0.5 flex items-center gap-1.5 text-[12.5px] text-muted">
                            <span className="h-1.5 w-1.5 rounded-full" style={{ background: STATUS_COLOR[s.status] }} />
                            <span>{t(`status_${s.status}`)}</span>
                            <span className="text-faint">·</span>
                            <span className="truncate">{t("updated", { t: relativeTime(s.last_success_at) })}</span>
                          </div>
                        </div>
                        <span className="text-[12.5px] text-faint tabular-nums">{s.article_count}</span>
                        <ChevronRight size={18} className="text-faint" />
                      </button>
                    </li>
                  ))}
                </ul>
              </section>
            );
          })}
        </div>
      )}
    </div>
  );
}
