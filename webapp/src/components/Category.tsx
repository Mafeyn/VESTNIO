import type { CategoryId } from "../lib/api";
import { t } from "../lib/i18n";
import { ChipIcon, GamepadIcon, GlobeIcon } from "./Icons";

export const CATEGORIES: CategoryId[] = ["world", "technology", "gaming"];

export function CategoryGlyph({ category, size = 18 }: { category: CategoryId; size?: number }) {
  if (category === "gaming") return <GamepadIcon size={size} />;
  if (category === "world") return <GlobeIcon size={size} />;
  return <ChipIcon size={size} />;
}

export function CategoryTag({ category }: { category: CategoryId }) {
  return (
    <span
      className="inline-flex items-center gap-1.5 text-[11px] font-semibold tracking-[0.08em] uppercase"
      style={{ color: `var(--c-${category})` }}
    >
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: `var(--c-${category})` }} />
      {t(category)}
    </span>
  );
}
