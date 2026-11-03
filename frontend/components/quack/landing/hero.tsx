"use client";

import { ChevronDown } from "lucide-react";
import Link from "next/link";
import { useT } from "@/lib/i18n/provider";

/** Первый экран лендинга: заголовок, подзаголовок и кнопка; утка и графы рисует общий фон (Backdrop) */
export function Hero() {
  const t = useT().landing;

  const head = t.title.slice(0, -1);
  const mark = t.title.slice(-1);

  return (
    <section id="top" className="relative h-full shrink-0 overflow-hidden">
      <div className="relative mx-auto flex max-w-3xl flex-col items-center gap-5 px-6 pt-24 text-center sm:pt-28 lg:pt-32">
        <h1 className="font-mono text-[clamp(3.5rem,11vw,8.5rem)] font-extrabold leading-[0.85] tracking-[-0.06em] text-[#f6eadc] [text-shadow:0_0_40px_#ff7a1a40]">
          {head}
          <span className="text-[#ff8a2a]">{mark}</span>
        </h1>
        <p className="max-w-[30ch] font-mono text-[clamp(0.9375rem,1.4vw,1.1875rem)] leading-snug tracking-[-0.01em] text-[#bba995]">{t.tagline}</p>
        <Link
          href="/signup"
          className="mt-3 inline-flex h-16 w-[13.75rem] items-center justify-center rounded-pill bg-[#ff8a2a] font-mono text-[1.5rem] font-bold leading-none tracking-[-0.03em] text-[#1a0a02] shadow-[0_0_40px_#ff7a1a55] transition-[background-color,transform] duration-(--dur-s) ease-(--ease-out) outline-none hover:bg-[#ff9d4d] focus-visible:ring-4 focus-visible:ring-[#ff8a2a]/50 active:translate-y-px sm:h-[4.5rem] sm:w-[15.5rem] sm:text-[1.625rem]"
        >
          {t.cta}
        </Link>
      </div>

      <button
        type="button"
        aria-label={t.scroll}
        onClick={(e) => {
          const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
          e.currentTarget.closest("section")?.nextElementSibling?.scrollIntoView({ behavior: reduced ? "auto" : "smooth" });
        }}
        className="absolute bottom-3 left-1/2 flex size-12 -translate-x-1/2 items-center justify-center rounded-pill text-[#bba995] outline-none transition-colors duration-(--dur-s) hover:text-[#f6eadc] focus-visible:ring-2 focus-visible:ring-[#ff8a2a]/60"
      >
        <ChevronDown aria-hidden className="size-6 motion-safe:animate-bounce" />
      </button>
    </section>
  );
}
