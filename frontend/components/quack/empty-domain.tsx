"use client";

import { useT } from "@/lib/i18n/provider";
import { Duck } from "./duck";

/** Первый заход: графа нет — утка, короткий текст, поле ввода ниже. Граф растёт из первых сессий и материалов */
export function EmptyDomain({ titleDat }: { titleDat: string }) {
  const t = useT();
  return (
    <div className="flex flex-1 items-center">
      <div className="flex max-w-xl flex-col gap-6 sm:flex-row sm:items-center sm:gap-8">
        <Duck className="w-28 sm:w-36" />
        <div>
          <h2 className="font-semibold text-paper">{t.empty.title}</h2>
          <p className="mt-1 text-paper-dim">{t.empty.body(titleDat)}</p>
        </div>
      </div>
    </div>
  );
}
