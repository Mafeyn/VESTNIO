import { useState } from "react";
import type { CategoryId } from "../lib/api";
import { CategoryGlyph } from "./Category";

interface Props {
  src: string | null;
  alt?: string;
  source: string;
  category: CategoryId;
  className?: string;
  eager?: boolean;
  sizes?: "lg" | "sm";
  /** compact cards: if the image fails to load, render nothing instead of a fallback tile */
  hideOnError?: boolean;
}

/**
 * Lazy-loaded article image. When a publisher gives no image, or it fails to load,
 * we show a quiet branded tile (category glyph + publisher name) instead of a broken box.
 */
export function ArticleImage({ src, alt = "", source, category, className = "", eager, sizes = "lg", hideOnError }: Props) {
  const [failed, setFailed] = useState(false);
  const [loaded, setLoaded] = useState(false);

  if (failed && hideOnError) return null;
  if (!src || failed) {
    return (
      <div
        className={`relative flex items-center justify-center overflow-hidden ${className}`}
        style={{
          background: `radial-gradient(120% 90% at 0% 0%, color-mix(in oklab, var(--c-${category}) 34%, transparent), transparent 60%), linear-gradient(135deg, var(--surface-2), var(--surface-3))`,
        }}
        role="img"
        aria-label={source}
      >
        <div className="flex w-full flex-col items-center gap-1.5 text-center" style={{ color: `var(--c-${category})` }}>
          <CategoryGlyph category={category} size={sizes === "lg" ? 30 : 22} />
          {sizes === "lg" && (
            <span className="max-w-[80%] truncate text-[11px] font-semibold tracking-[0.12em] text-muted uppercase">
              {source}
            </span>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className={`relative overflow-hidden bg-surface-2 ${className}`}>
      <img
        src={src}
        alt={alt}
        loading={eager ? "eager" : "lazy"}
        decoding="async"
        referrerPolicy="no-referrer"
        // eslint-disable-next-line react/no-unknown-property
        fetchPriority={eager ? "high" : "auto"}
        data-loaded={loaded}
        onLoad={() => setLoaded(true)}
        onError={() => setFailed(true)}
        className="lazy-img absolute inset-0 h-full w-full object-cover"
      />
    </div>
  );
}
