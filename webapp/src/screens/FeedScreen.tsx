import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { ActiveSourcePills, CategoryChips, FilterButton, FilterSheet, SearchBar } from "../components/FeedControls";
import { CompactCard, FeaturedCard } from "../components/ArticleCard";
import { RefreshIcon, SearchIcon } from "../components/Icons";
import { Brand } from "../components/Navigation";
import { CompactSkeleton, ErrorView, FeaturedSkeleton, PrimaryButton, StateView } from "../components/States";
import { api } from "../lib/api";
import { t } from "../lib/i18n";
import { restoreScroll } from "../lib/router";
import { filters, useFilters } from "../lib/store";
import { haptic } from "../lib/telegram";
import { useOnline } from "../lib/useOnline";

const PAGE = 20;

export function FeedScreen() {
  const f = useFilters();
  const online = useOnline();
  const [sheet, setSheet] = useState(false);
  const sources = useQuery({ queryKey: ["sources"], queryFn: ({ signal }) => api.sources(signal), staleTime: 120_000 });

  const feed = useInfiniteQuery({
    queryKey: ["articles", f.category, f.sources, f.q.trim(), f.sort],
    queryFn: ({ pageParam, signal }) =>
      api.articles({ category: f.category, sources: f.sources, q: f.q, sort: f.sort, cursor: pageParam, limit: PAGE }, signal),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.meta?.next_cursor ?? undefined,
    staleTime: 60_000,
    refetchInterval: 5 * 60_000, // keep an open feed fresh without user action
    maxPages: 15,
  });

  const all = feed.data?.pages.flatMap((p) => p.data) ?? [];
  const searching = Boolean(f.q.trim());
  // Featured slot: the newest story among the first few that has a real image.
  // (prefer properly dated items; never feature a story without a picture)
  let featuredIdx = !searching && f.sort === "newest" ? all.findIndex((a) => a.image_url && !a.published_estimated) : -1;
  if (featuredIdx < 0 && !searching && f.sort === "newest") featuredIdx = all.findIndex((a) => a.image_url);
  const showFeatured = featuredIdx >= 0;
  const items = showFeatured ? [all[featuredIdx], ...all.filter((_, i) => i !== featuredIdx)] : all;

  // scroll restoration: once cached content is on screen
  const restored = useRef(false);
  useLayoutEffect(() => {
    if (!restored.current && items.length) {
      restored.current = true;
      restoreScroll();
    }
  }, [items.length]);

  // infinite scroll
  const sentinel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = sentinel.current;
    if (!el) return;
    const io = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && feed.hasNextPage && !feed.isFetchingNextPage) feed.fetchNextPage();
      },
      { rootMargin: "800px 0px" },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [feed.hasNextPage, feed.isFetchingNextPage, feed.fetchNextPage]);

  const refresh = async () => {
    haptic.tap();
    window.scrollTo({ top: 0, behavior: "smooth" });
    await feed.refetch();
  };

  return (
    <div className="screen-enter">
      <header className="glass sticky top-0 z-20 -mx-4 border-b border-line px-4 pt-safe lg:-mx-8 lg:px-8">
        <div className="flex h-[52px] items-center justify-between lg:hidden">
          <Brand />
          <button
            type="button"
            onClick={refresh}
            aria-label={t("refresh")}
            className="press grid h-10 w-10 place-items-center rounded-full text-muted"
          >
            <RefreshIcon size={20} className={feed.isRefetching && !feed.isFetchingNextPage ? "animate-spin" : ""} />
          </button>
        </div>
        <div className="flex gap-2 pb-3 lg:pt-6">
          <SearchBar />
          <FilterButton onClick={() => setSheet(true)} />
          <button
            type="button"
            onClick={refresh}
            aria-label={t("refresh")}
            className="press hidden h-11 w-11 shrink-0 place-items-center rounded-[14px] border border-line bg-surface text-muted lg:grid"
          >
            <RefreshIcon size={19} className={feed.isRefetching && !feed.isFetchingNextPage ? "animate-spin" : ""} />
          </button>
        </div>
        <div className="flex flex-col gap-2.5 pb-3">
          <CategoryChips />
          <ActiveSourcePills sources={sources.data?.data ?? []} />
        </div>
      </header>

      {!online && items.length > 0 && (
        <div className="fade-in mt-3 rounded-[14px] border border-warn/30 bg-warn/10 px-4 py-2.5 text-[13px] text-warn">
          {t("offlineTitle")}
        </div>
      )}

      <main className="pt-4">
        {feed.isPending ? (
          <FeedSkeleton />
        ) : feed.isError && !items.length ? (
          <ErrorView error={feed.error} onRetry={() => feed.refetch()} />
        ) : items.length === 0 ? (
          searching ? (
            <StateView icon={<SearchIcon size={28} />} title={t("emptySearchTitle", { q: f.q.trim() })} text={t("emptySearchText")} />
          ) : (
            <StateView
              icon={<SearchIcon size={28} />}
              title={t("emptyFeedTitle")}
              text={t("emptyFeedText")}
              action={
                (f.category || f.sources.length > 0) && (
                  <PrimaryButton onClick={() => filters.set({ category: null, sources: [] })}>{t("clear")}</PrimaryButton>
                )
              }
            />
          )
        ) : (
          <>
            {showFeatured && (
              <div className="mb-3 lg:mb-5">
                <FeaturedCard article={items[0]} />
              </div>
            )}
            {showFeatured && <h2 className="mt-5 mb-1 px-1 text-[13px] font-semibold tracking-[0.1em] text-faint uppercase lg:hidden">{t("newStories")}</h2>}
            <div className="flex flex-col lg:grid lg:grid-cols-2 lg:gap-3 2xl:grid-cols-3">
              {(showFeatured ? items.slice(1) : items).map((a) => (
                <CompactCard key={a.id} article={a} />
              ))}
            </div>
            <div ref={sentinel} className="h-px" />
            <div className="py-8 text-center text-[13px] text-faint">
              {feed.isFetchingNextPage ? (
                <div className="flex flex-col">
                  <CompactSkeleton />
                  <CompactSkeleton />
                </div>
              ) : feed.isError ? (
                <button type="button" onClick={() => feed.fetchNextPage()} className="text-accent-ink">
                  {t("retry")}
                </button>
              ) : !feed.hasNextPage ? (
                t("endOfFeed")
              ) : null}
            </div>
          </>
        )}
      </main>
      <FilterSheet open={sheet} onClose={() => setSheet(false)} />
    </div>
  );
}

function FeedSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading">
      <FeaturedSkeleton />
      <div className="mt-4 flex flex-col lg:grid lg:grid-cols-2 lg:gap-3">
        {Array.from({ length: 6 }, (_, i) => (
          <CompactSkeleton key={i} />
        ))}
      </div>
    </div>
  );
}
