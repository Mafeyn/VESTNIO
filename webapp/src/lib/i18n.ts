/** UI strings in English and Russian. Article text is never translated. */
import { uiLanguage } from "./telegram";

const en = {
  feed: "Feed",
  categories: "Categories",
  sources: "Sources",
  saved: "Saved",
  all: "All",
  gaming: "Gaming",
  world: "World",
  technology: "Technology",
  searchPlaceholder: "Search news",
  newest: "Newest",
  oldest: "Oldest",
  relevance: "Most relevant",
  filters: "Filters",
  allSources: "All sources",
  clear: "Clear",
  apply: "Show results",
  readOriginal: "Read on {source}",
  openInTelegram: "Open in Telegram",
  save: "Save",
  unsave: "Saved",
  topStory: "Top story",
  loadingMore: "Loading more…",
  endOfFeed: "You're all caught up",
  emptyFeedTitle: "No articles here yet",
  emptyFeedText: "Try another category or clear your filters.",
  emptySearchTitle: "Nothing matches “{q}”",
  emptySearchText: "Check the spelling or search for a shorter word.",
  emptySavedTitle: "No saved articles",
  emptySavedText: "Tap the bookmark on any story to keep it here. Saved stories stay on this device.",
  offlineTitle: "You're offline",
  errorTitle: "Couldn't load the news",
  errorText: "Check your connection and try again.",
  retry: "Try again",
  refresh: "Refresh",
  articlesToday: "{n} today",
  articlesTotal: "{n} articles",
  sourcesCount: "{n} sources",
  updated: "Updated {t}",
  never: "never",
  status_healthy: "Working",
  status_degraded: "Unstable",
  status_failing: "Failing",
  status_pending: "Waiting",
  status_disabled: "Off",
  every: "every {n} min",
  firstSeen: "first seen",
  excerptUnavailable: "The publisher doesn't offer an excerpt. Open the original to read the story.",
  notFound: "This article is no longer available.",
  backToFeed: "Back to feed",
  showInFeed: "Show in feed",
  justNow: "just now",
  newStories: "New stories",
};

type Dict = typeof en;

const ru: Dict = {
  feed: "Лента",
  categories: "Категории",
  sources: "Источники",
  saved: "Закладки",
  all: "Все",
  gaming: "Игры",
  world: "Мир",
  technology: "Технологии",
  searchPlaceholder: "Поиск новостей",
  newest: "Сначала новые",
  oldest: "Сначала старые",
  relevance: "По релевантности",
  filters: "Фильтры",
  allSources: "Все источники",
  clear: "Сбросить",
  apply: "Показать",
  readOriginal: "Читать на {source}",
  openInTelegram: "Открыть в Telegram",
  save: "Сохранить",
  unsave: "Сохранено",
  topStory: "Главное",
  loadingMore: "Загружаем ещё…",
  endOfFeed: "Вы всё прочитали",
  emptyFeedTitle: "Здесь пока нет статей",
  emptyFeedText: "Выберите другую категорию или сбросьте фильтры.",
  emptySearchTitle: "По запросу «{q}» ничего нет",
  emptySearchText: "Проверьте написание или попробуйте слово короче. Статьи на языке оригинала.",
  emptySavedTitle: "Нет сохранённых статей",
  emptySavedText: "Нажмите на закладку у любой новости, чтобы сохранить её. Закладки хранятся на этом устройстве.",
  offlineTitle: "Нет подключения",
  errorTitle: "Не удалось загрузить новости",
  errorText: "Проверьте соединение и попробуйте ещё раз.",
  retry: "Повторить",
  refresh: "Обновить",
  articlesToday: "{n} за сутки",
  articlesTotal: "{n} статей",
  sourcesCount: "{n} источников",
  updated: "Обновлено {t}",
  never: "никогда",
  status_healthy: "Работает",
  status_degraded: "Нестабилен",
  status_failing: "Ошибка",
  status_pending: "Ожидание",
  status_disabled: "Выключен",
  every: "каждые {n} мин",
  firstSeen: "обнаружено",
  excerptUnavailable: "Издатель не предоставляет описание. Откройте оригинал, чтобы прочитать новость.",
  notFound: "Эта статья больше недоступна.",
  backToFeed: "Вернуться в ленту",
  showInFeed: "Показать в ленте",
  justNow: "только что",
  newStories: "Свежие новости",
};

export const locale = uiLanguage().toLowerCase().startsWith("ru") ? "ru" : "en";
const dict: Dict = locale === "ru" ? ru : en;
document.documentElement.lang = locale;

export type Key = keyof Dict;

export function t(key: Key, vars?: Record<string, string | number>): string {
  let s = dict[key];
  if (vars) for (const [k, v] of Object.entries(vars)) s = s.replace(`{${k}}`, String(v));
  return s;
}

const rtf = new Intl.RelativeTimeFormat(locale, { numeric: "auto", style: "short" });
const abs = new Intl.DateTimeFormat(locale, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const full = new Intl.DateTimeFormat(locale, { dateStyle: "long", timeStyle: "short" });

/** "5 min ago", "3 hr ago", then an absolute date after a week. Input is UTC ISO. */
export function relativeTime(iso: string | null, now = Date.now()): string {
  if (!iso) return t("never");
  const diff = (new Date(iso).getTime() - now) / 1000;
  const a = Math.abs(diff);
  if (a < 60) return t("justNow");
  if (a < 3600) return rtf.format(Math.round(diff / 60), "minute");
  if (a < 86400) return rtf.format(Math.round(diff / 3600), "hour");
  if (a < 7 * 86400) return rtf.format(Math.round(diff / 86400), "day");
  return abs.format(new Date(iso));
}

export function fullDate(iso: string): string {
  return full.format(new Date(iso));
}
