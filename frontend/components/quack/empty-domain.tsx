"use client";

import Link from "next/link";
import { useT } from "@/lib/i18n/provider";
import { Duck } from "./duck";

/** Первый заход: графа нет — большая полосатая утка, подписи капсом, заголовок, поле ввода ниже.
 *  Композиция как у прелоадера: спокойно, по центру, шторка при появлении.
 *  setupHref: предмет на бэкенде ещё не настроен (темы не подтверждены) — ведём довести настройку */
export function EmptyDomain({ titleDat, setupHref }: { titleDat: string; setupHref?: string }) {
  const t = useT();
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-6 py-6 text-center">
      <p className="caps flex flex-wrap justify-center gap-x-3 text-paper-dim">
        <span>{t.preloader.kindTop}</span>
        <span aria-hidden>/</span>
        <span>{t.preloader.kindBottom}</span>
      </p>
      <div className="mask-wipe animate-wipe-in">
        <Duck className="w-48 sm:w-64" striped />
      </div>
      <div className="flex max-w-md flex-col items-center gap-3">
        <h2 className="display-caps text-display text-paper">{setupHref ? t.live.setupTitle : t.empty.title}</h2>
        <p className="text-paper-dim">{setupHref ? t.live.setupBody : titleDat ? t.empty.body(titleDat) : t.empty.bodyAny}</p>
        {setupHref && (
          <Link
            href={setupHref}
            className="caps mt-3 inline-flex h-10 items-center rounded-pill bg-ribbon px-6 text-on-ribbon transition-colors duration-[var(--dur-s)] ease-out hover:bg-ribbon-hover"
          >
            {t.live.setupCta}
          </Link>
        )}
      </div>
    </div>
  );
}
