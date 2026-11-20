import { memo, type MouseEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { Article } from "../lib/api";
import { relativeTime, t } from "../lib/i18n";
import { navigate } from "../lib/router";
import { toggleBookmark, useIsSaved } from "../lib/store";
import { haptic } from "../lib/telegram";
import { ArticleImage } from "./ArticleImage";
import { CategoryTag } from "./Category";
import { BookmarkIcon } from "./Icons";

function useOpenArticle(article: Article) {
  const qc = useQueryClient();
  return () => {
    // detail screen renders instantly from the feed item, then refreshes in background
    qc.setQueryData(["article", article.id], (old: Article | undefined) => old ?? article);
    haptic.tap();
    navigate(`/article/${article.id}`);
  };
}

export function BookmarkButton({ article, className = "" }: { article: Article; className?: string }) {
  const saved = useIsSaved(article.id);
  const onClick = (e: MouseEvent) => {
    e.stopPropagation();
    toggleBookmark(article);
    haptic.select();
  };
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={saved}
      aria-label={saved ? t("unsave") : t("save")}
      className={`press -m-2 grid h-10 w-10 shrink-0 place-items-center rounded-full ${saved ? "text-accent-ink" : "text-faint hover:text-muted"} ${className}`}
    >
      <BookmarkIcon size={20} filled={saved} />
    </button>
  );
}

function Meta({ article }: { article: Article }) {
  return (
    <div className="flex min-w-0 items-center gap-1.5 text-[12.5px] text-muted">
      <span className="truncate font-medium text-text/85">{article.source.name}</span>
      <span className="text-faint">·</span>
      <time
        dateTime={article.published_at}
        title={article.published_estimated ? t("firstSeen") : undefined}
        className="shrink-0 tabular-nums"
      >
        {relativeTime(article.published_at)}
      </time>
    </div>
  );
}

export const FeaturedCard = memo(function FeaturedCard({ article }: { article: Article }) {
  const open = useOpenArticle(article);
  return (
    <article
      onClick={open}
      className="card press group cursor-pointer overflow-hidden rounded-[22px] lg:grid lg:grid-cols-[1.35fr_1fr]"
      aria-label={article.title}
    >
      <ArticleImage
        src={article.image_url}
        source={article.source.name}
        category={article.category}
        className="aspect-[16/9] w-full lg:aspect-auto lg:h-full lg:min-h-[340px]"
        eager
      />
      <div className="flex flex-col gap-2.5 p-4 pb-3.5 sm:p-5 lg:justify-center lg:gap-3.5 lg:p-8">
        <div className="flex items-center justify-between">
          <span className="rounded-full bg-accent-soft px-2.5 py-1 text-[11px] font-semibold tracking-[0.08em] text-accent-ink uppercase">
            {t("topStory")}
          </span>
          <CategoryTag category={article.category} />
        </div>
        <h2 className="font-display text-[21px] leading-[1.22] font-semibold tracking-[-0.015em] text-balance sm:text-[24px]">
          <a href={article.url} onClick={(e) => e.preventDefault()} className="outline-none">
            {article.title}
          </a>
        </h2>
        {article.summary && <p className="line-clamp-3 text-[14.5px] leading-[1.5] text-muted">{article.summary}</p>}
        <div className="mt-0.5 flex items-center justify-between gap-3">
          <Meta article={article} />
          <BookmarkButton article={article} />
        </div>
      </div>
    </article>
  );
});

export const CompactCard = memo(function CompactCard({ article }: { article: Article }) {
  const open = useOpenArticle(article);
  return (
    <article
      onClick={open}
      className="press group flex cursor-pointer gap-3.5 rounded-[18px] p-3 transition-colors hover:bg-surface sm:card"
      aria-label={article.title}
    >
      <div className="flex min-w-0 flex-1 flex-col gap-1.5">
        <CategoryTag category={article.category} />
        <h3 className="line-clamp-3 text-[15.5px] leading-[1.32] font-semibold tracking-[-0.008em] text-pretty">
          {article.title}
        </h3>
        {!article.image_url && article.summary && (
          <p className="line-clamp-2 text-[13.5px] leading-[1.45] text-muted">{article.summary}</p>
        )}
        <div className="mt-auto flex items-center justify-between gap-2 pt-0.5">
          <Meta article={article} />
          <BookmarkButton article={article} />
        </div>
      </div>
      {/* no picture from the publisher → text-only card (no empty placeholder square) */}
      {article.image_url && (
        <ArticleImage
          src={article.image_url}
          source={article.source.name}
          category={article.category}
          className="h-[92px] w-[92px] shrink-0 rounded-[14px] sm:h-[104px] sm:w-[124px]"
          sizes="sm"
          hideOnError
        />
      )}
    </article>
  );
});
