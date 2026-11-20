import { lazy, Suspense, useEffect } from "react";
import { BottomNav, Sidebar } from "./components/Navigation";
import { useRoute } from "./lib/router";
import { setBackButton } from "./lib/telegram";
import { FeedScreen } from "./screens/FeedScreen";

// Secondary screens are split out to keep the startup bundle small.
const ArticleScreen = lazy(() => import("./screens/ArticleScreen").then((m) => ({ default: m.ArticleScreen })));
const CategoriesScreen = lazy(() => import("./screens/CategoriesScreen").then((m) => ({ default: m.CategoriesScreen })));
const SourcesScreen = lazy(() => import("./screens/SourcesScreen").then((m) => ({ default: m.SourcesScreen })));
const SavedScreen = lazy(() => import("./screens/SavedScreen").then((m) => ({ default: m.SavedScreen })));

export function App() {
  const route = useRoute();
  const isArticle = route.name === "article";

  // top-level tabs never show Telegram's BackButton; ArticleScreen enables it
  useEffect(() => {
    if (!isArticle) setBackButton(null);
  }, [isArticle]);

  return (
    <div className="mx-auto flex min-h-[var(--tg-vh,100dvh)] max-w-[1440px]">
      <Sidebar route={route} />
      <div className={`min-w-0 flex-1 px-safe lg:px-8 ${isArticle ? "pb-8" : "pb-[calc(76px+max(var(--safe-bottom,0px),env(safe-area-inset-bottom,0px)))] lg:pb-10"}`}>
        <div className={isArticle ? "" : "mx-auto max-w-[1080px]"}>
          <Suspense fallback={null}>
            {route.name === "feed" && <FeedScreen />}
            {route.name === "categories" && <CategoriesScreen />}
            {route.name === "sources" && <SourcesScreen />}
            {route.name === "saved" && <SavedScreen />}
            {route.name === "article" && <ArticleScreen key={route.id} id={route.id} />}
          </Suspense>
        </div>
      </div>
      {!isArticle && <BottomNav route={route} />}
    </div>
  );
}
