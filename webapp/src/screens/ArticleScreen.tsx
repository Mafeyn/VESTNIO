import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { BookmarkButton } from "../components/ArticleCard";
import { ArticleImage } from "../components/ArticleImage";
import { CategoryTag } from "../components/Category";
import { ChevronLeft, ExternalIcon } from "../components/Icons";
import { ErrorView, PrimaryButton, StateView } from "../components/States";
import { ApiError, api } from "../lib/api";
import { fullDate, relativeTime, t } from "../lib/i18n";
import { back } from "../lib/router";
import { useBookmarks } from "../lib/store";
import { haptic, isTelegram, isTelegramUrl, openExternal, setBackButton } from "../lib/telegram";

export function ArticleScreen({ id }: { id: number }) {
  const saved = useBookmarks().find((b) => b.id === id);
  const q = useQuery({
    queryKey: ["article", id],
    queryFn: ({ signal }) => api.article(id, signal).then((r) => r.data),
    placeholderData: saved, // bookmarks open instantly, even offline
    staleTime: 5 * 60_000,
  });

  useEffect(() => setBackButton(back), []); // native Telegram BackButton

  const a = q.data;
  if (!a) {
    if (q.isError) {
      const gone = q.error instanceof ApiError && q.error.status === 404;
      return gone ? (
        <StateView title={t("notFound")} icon={<ChevronLeft size={28} />} action={<PrimaryButton onClick={back}>{t("backToFeed")}</PrimaryButton>} />
      ) : (
        <ErrorView error={q.error} onRetry={() => q.refetch()} />
      );
    }
    return <ArticleSkeleton />;
  }

  const read = () => {
    haptic.tap();
    openExternal(a.url);
  };
  let host = a.source.name;
  try {
    host = new URL(a.url).hostname.replace(/^www\./, "");
  } catch {
    /* keep source name */
  }

  return (
    <article className="screen-enter mx-auto w-full max-w-[720px] pt-safe pb-10">
      {!isTelegram && (
        <button type="button" onClick={back} className="mt-4 -ml-2 inline-flex h-10 items-center gap-1 rounded-full pr-3 pl-1 text-[14px] text-muted hover:text-text">
          <ChevronLeft size={20} /> {t("feed")}
        </button>
      )}
      <ArticleImage
        src={a.image_url}
        alt=""
        source={a.source.name}
        category={a.category}
        eager
        className="-mx-4 mt-3 aspect-[16/9] sm:mx-0 sm:rounded-[22px]"
      />
      <div className="mt-5 flex items-center justify-between">
        <CategoryTag category={a.category} />
        <BookmarkButton article={a} />
      </div>
      <h1 className="font-display mt-2 text-[26px] leading-[1.18] font-bold tracking-[-0.022em] text-balance sm:text-[32px]">
        {a.title}
      </h1>
      <div className="mt-4 flex flex-wrap items-center gap-x-2 gap-y-1 text-[13.5px] text-muted">
        <span className="font-semibold text-text">{a.source.name}</span>
        <span className="text-faint">·</span>
        <time dateTime={a.published_at} title={fullDate(a.published_at)}>
          {a.published_estimated ? `${t("firstSeen")} ` : ""}
          {relativeTime(a.published_at)}
        </time>
        {a.language && (
          <>
            <span className="text-faint">·</span>
            <span className="uppercase">{a.language.split("-")[0]}</span>
          </>
        )}
      </div>

      <div className="mt-6 border-t border-line pt-6">
        {a.summary ? (
          <p className="text-[17px] leading-[1.62] text-text/90" lang={a.language ?? undefined}>
            {a.summary}
          </p>
        ) : (
          <p className="text-[15px] leading-relaxed text-muted">{t("excerptUnavailable")}</p>
        )}
      </div>

      <button
        type="button"
        onClick={read}
        className="press mt-8 flex h-[54px] w-full items-center justify-center gap-2 rounded-[16px] bg-accent text-[16px] font-semibold text-white shadow-[0_14px_34px_-14px_var(--accent)]"
      >
        {isTelegramUrl(a.url) ? t("openInTelegram") : t("readOriginal", { source: a.source.name })}
        <ExternalIcon size={18} />
      </button>
      <p className="mt-3 text-center text-[12.5px] text-faint">{host}</p>
    </article>
  );
}

function ArticleSkeleton() {
  return (
    <div className="mx-auto w-full max-w-[720px] pt-safe" aria-busy="true">
      <div className="skeleton -mx-4 mt-3 aspect-[16/9] rounded-none sm:mx-0 sm:rounded-[22px]" />
      <div className="skeleton mt-6 h-3 w-24" />
      <div className="skeleton mt-4 h-8 w-11/12" />
      <div className="skeleton mt-2 h-8 w-2/3" />
      <div className="skeleton mt-5 h-4 w-1/2" />
      <div className="mt-8 flex flex-col gap-3">
        <div className="skeleton h-4 w-full" />
        <div className="skeleton h-4 w-full" />
        <div className="skeleton h-4 w-4/5" />
      </div>
    </div>
  );
}
