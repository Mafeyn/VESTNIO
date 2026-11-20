import { useLayoutEffect } from "react";
import { CompactCard } from "../components/ArticleCard";
import { BookmarkIcon } from "../components/Icons";
import { StateView } from "../components/States";
import { t } from "../lib/i18n";
import { restoreScroll } from "../lib/router";
import { useBookmarks } from "../lib/store";
import { ScreenHeader } from "./ScreenHeader";

export function SavedScreen() {
  const items = useBookmarks();
  useLayoutEffect(() => restoreScroll(), []);
  return (
    <div className="screen-enter">
      <ScreenHeader title={t("saved")} aside={items.length > 0 && <span className="pb-1 text-[13px] text-faint tabular-nums">{items.length}</span>} />
      {items.length === 0 ? (
        <StateView icon={<BookmarkIcon size={28} />} title={t("emptySavedTitle")} text={t("emptySavedText")} />
      ) : (
        <div className="-mx-3 flex flex-col sm:mx-0 lg:grid lg:grid-cols-2 lg:gap-3">
          {items.map((a) => (
            <CompactCard key={a.id} article={a} />
          ))}
        </div>
      )}
    </div>
  );
}
