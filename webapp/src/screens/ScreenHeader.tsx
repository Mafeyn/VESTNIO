import type { ReactNode } from "react";

export function ScreenHeader({ title, aside }: { title: string; aside?: ReactNode }) {
  return (
    <header className="flex items-end justify-between pt-safe pb-4">
      <h1 className="font-display mt-5 text-[30px] leading-none font-bold tracking-[-0.025em] lg:mt-8">{title}</h1>
      {aside}
    </header>
  );
}
