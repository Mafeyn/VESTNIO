/**
 * Thin typed wrapper over the official Telegram Mini Apps SDK (telegram-web-app.js).
 * Everything degrades gracefully when the app is opened in a normal browser.
 *
 * Security note: initDataUnsafe is used only for cosmetic things (UI language).
 * Anything that needs identity sends the signed `initData` string to the backend.
 */

type EventName =
  | "themeChanged"
  | "viewportChanged"
  | "safeAreaChanged"
  | "contentSafeAreaChanged"
  | "backButtonClicked"
  | "activated"
  | "fullscreenChanged";

interface Insets {
  top: number;
  bottom: number;
  left: number;
  right: number;
}

interface TgWebApp {
  initData: string;
  initDataUnsafe: { user?: { language_code?: string }; start_param?: string };
  version: string;
  platform: string;
  colorScheme: "light" | "dark";
  themeParams: Record<string, string | undefined>;
  isExpanded: boolean;
  viewportHeight: number;
  viewportStableHeight: number;
  safeAreaInset?: Insets;
  contentSafeAreaInset?: Insets;
  ready(): void;
  expand(): void;
  isVersionAtLeast(v: string): boolean;
  setHeaderColor(color: string): void;
  setBackgroundColor(color: string): void;
  setBottomBarColor?(color: string): void;
  disableVerticalSwipes?(): void;
  openLink(url: string, options?: { try_instant_view?: boolean }): void;
  openTelegramLink?(url: string): void;
  onEvent(e: EventName, cb: () => void): void;
  offEvent(e: EventName, cb: () => void): void;
  BackButton: { show(): void; hide(): void; onClick(cb: () => void): void; offClick(cb: () => void): void };
  HapticFeedback?: {
    impactOccurred(style: "light" | "medium" | "heavy" | "rigid" | "soft"): void;
    selectionChanged(): void;
    notificationOccurred(type: "error" | "success" | "warning"): void;
  };
}

declare global {
  interface Window {
    Telegram?: { WebApp?: TgWebApp };
  }
}

const tg: TgWebApp | undefined = (() => {
  const app = window.Telegram?.WebApp;
  // The script defines WebApp even in a normal browser; initData is only set inside Telegram.
  return app && app.initData ? app : undefined;
})();

export const isTelegram = Boolean(tg);
export const platform = tg?.platform ?? "web";

const supports = (v: string) => Boolean(tg?.isVersionAtLeast?.(v));

// ------------------------------------------------------------------- theme
export type Scheme = "dark" | "light";

const PALETTE: Record<Scheme, { bg: string; surface: string }> = {
  dark: { bg: "#0E1019", surface: "#191C29" },
  light: { bg: "#F4F4F8", surface: "#FFFFFF" },
};

function systemScheme(): Scheme {
  return window.matchMedia?.("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

export function currentScheme(): Scheme {
  return tg ? tg.colorScheme : systemScheme();
}

function applyScheme() {
  const scheme = currentScheme();
  const root = document.documentElement;
  root.dataset.theme = scheme;
  root.style.colorScheme = scheme;
  const { bg } = PALETTE[scheme];
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", bg);
  if (tg && supports("6.1")) {
    tg.setHeaderColor(bg);
    tg.setBackgroundColor(bg);
    if (supports("7.10")) tg.setBottomBarColor?.(bg);
  }
}

// ------------------------------------------------------- viewport + insets
function applyViewport() {
  const root = document.documentElement.style;
  if (tg) {
    root.setProperty("--tg-vh", `${tg.viewportStableHeight || window.innerHeight}px`);
    const sa = tg.safeAreaInset ?? { top: 0, bottom: 0, left: 0, right: 0 };
    const csa = tg.contentSafeAreaInset ?? { top: 0, bottom: 0, left: 0, right: 0 };
    // device safe area + Telegram's own overlay (fullscreen header controls)
    root.setProperty("--safe-top", `${sa.top + csa.top}px`);
    root.setProperty("--safe-bottom", `${sa.bottom + csa.bottom}px`);
    root.setProperty("--safe-left", `${sa.left + csa.left}px`);
    root.setProperty("--safe-right", `${sa.right + csa.right}px`);
  } else {
    root.setProperty("--tg-vh", "100dvh");
  }
}

export function initTelegram() {
  applyScheme();
  applyViewport();
  if (!tg) {
    window.matchMedia?.("(prefers-color-scheme: light)").addEventListener("change", applyScheme);
    return;
  }
  tg.ready();
  tg.expand();
  // We scroll a long feed: stop vertical swipes from collapsing the app by accident.
  if (supports("7.7")) tg.disableVerticalSwipes?.();
  tg.onEvent("themeChanged", applyScheme);
  tg.onEvent("viewportChanged", applyViewport);
  tg.onEvent("safeAreaChanged", applyViewport);
  tg.onEvent("contentSafeAreaChanged", applyViewport);
  tg.onEvent("fullscreenChanged", applyViewport);
}

// ----------------------------------------------------------- back button
export function setBackButton(handler: (() => void) | null): () => void {
  if (!tg || !supports("6.1")) return () => {};
  if (!handler) {
    tg.BackButton.hide();
    return () => {};
  }
  tg.BackButton.onClick(handler);
  tg.BackButton.show();
  return () => {
    tg.BackButton.offClick(handler);
    tg.BackButton.hide();
  };
}

// ---------------------------------------------------------------- links
export function isTelegramUrl(url: string): boolean {
  try {
    const host = new URL(url).hostname;
    return host === "t.me" || host === "telegram.me";
  } catch {
    return false;
  }
}

export function openExternal(url: string) {
  if (tg && isTelegramUrl(url) && tg.openTelegramLink && supports("6.1")) {
    tg.openTelegramLink(url); // channel posts open natively inside Telegram
  } else if (tg) {
    tg.openLink(url, { try_instant_view: false });
  } else {
    window.open(url, "_blank", "noopener,noreferrer");
  }
}

// --------------------------------------------------------------- haptics
export const haptic = {
  tap: () => tg?.HapticFeedback?.impactOccurred("light"),
  select: () => tg?.HapticFeedback?.selectionChanged(),
  success: () => tg?.HapticFeedback?.notificationOccurred("success"),
};

// ------------------------------------------------------------ cosmetics only
export function uiLanguage(): string {
  return tg?.initDataUnsafe.user?.language_code || navigator.language || "en";
}

/** `startapp` deep-link parameter, e.g. t.me/bot/app?startapp=article_123 */
export function startParam(): string | undefined {
  return tg?.initDataUnsafe.start_param || new URLSearchParams(location.search).get("tgWebAppStartParam") || undefined;
}

/** Signed initData for backend calls that need Telegram identity. */
export function signedInitData(): string | undefined {
  return tg?.initData || undefined;
}
