import type { ReactNode } from "react";
import { ApiError } from "../lib/api";
import { t } from "../lib/i18n";
import { OfflineIcon, RefreshIcon } from "./Icons";

export function FeaturedSkeleton() {
  return (
    <div className="card overflow-hidden rounded-[22px]" aria-hidden="true">
      <div className="skeleton aspect-[16/9] w-full rounded-none" />
      <div className="flex flex-col gap-3 p-4 sm:p-5">
        <div className="skeleton h-5 w-24 rounded-full" />
        <div className="skeleton h-6 w-11/12" />
        <div className="skeleton h-6 w-3/4" />
        <div className="skeleton h-4 w-full" />
        <div className="skeleton h-4 w-1/3" />
      </div>
    </div>
  );
}

export function CompactSkeleton() {
  return (
    <div className="flex gap-3.5 p-3" aria-hidden="true">
      <div className="flex flex-1 flex-col gap-2.5">
        <div className="skeleton h-3 w-20" />
        <div className="skeleton h-4 w-full" />
        <div className="skeleton h-4 w-4/5" />
        <div className="skeleton mt-1 h-3 w-1/3" />
      </div>
      <div className="skeleton h-[92px] w-[92px] shrink-0 rounded-[14px] sm:h-[104px] sm:w-[124px]" />
    </div>
  );
}

export function StateView({
  icon,
  title,
  text,
  action,
}: {
  icon: ReactNode;
  title: string;
  text?: string;
  action?: ReactNode;
}) {
  return (
    <div className="fade-in mx-auto flex max-w-sm flex-col items-center px-6 py-16 text-center">
      <div className="mb-5 grid h-16 w-16 place-items-center rounded-[20px] bg-surface text-accent-ink card">{icon}</div>
      <h3 className="text-[17px] font-semibold tracking-[-0.01em]">{title}</h3>
      {text && <p className="mt-1.5 text-[14px] leading-relaxed text-muted">{text}</p>}
      {action && <div className="mt-6">{action}</div>}
    </div>
  );
}

export function PrimaryButton({ children, onClick }: { children: ReactNode; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="press inline-flex h-11 items-center gap-2 rounded-full bg-accent px-5 text-[14.5px] font-semibold text-white shadow-[0_8px_24px_-10px_var(--accent)]"
    >
      {children}
    </button>
  );
}

export function ErrorView({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const offline = (error instanceof ApiError && error.isNetwork) || !navigator.onLine;
  return (
    <StateView
      icon={<OfflineIcon size={28} />}
      title={offline ? t("offlineTitle") : t("errorTitle")}
      text={offline ? t("errorText") : error instanceof ApiError && error.status >= 500 ? t("errorText") : String((error as Error)?.message ?? "")}
      action={
        <PrimaryButton onClick={onRetry}>
          <RefreshIcon size={18} /> {t("retry")}
        </PrimaryButton>
      }
    />
  );
}
