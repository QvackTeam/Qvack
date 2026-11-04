"use client";

import { useRef } from "react";
import { LandingFooter } from "./footer";
import { Hero } from "./hero";
import { LandingNav } from "./nav";
import { EfficiencyScene } from "./scenes/efficiency-scene";
import { GraphScene } from "./scenes/graph-scene";

/** Лендинг: панель, первый экран, две сцены (эффективность и память; как работает) и подвал. Прежние блоки и фон с графами пока не показываются (файлы остались). Страница прокручивается внутри этого контейнера, а не окном: у body overflow hidden */
export function LandingPage() {
  const scrollRef = useRef<HTMLElement>(null);
  return (
    <main
      ref={scrollRef}
      className="relative isolate h-full overflow-x-hidden overflow-y-auto bg-[#080504] text-[#f1e4d6] motion-safe:scroll-smooth"
    >
      <LandingNav scrollRef={scrollRef} />
      <Hero scrollRef={scrollRef} />
      <EfficiencyScene scrollRef={scrollRef} />
      <GraphScene scrollRef={scrollRef} />
      <LandingFooter />
    </main>
  );
}
