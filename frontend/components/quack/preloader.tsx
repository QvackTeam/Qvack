"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Duck as FlatDuck } from "@/components/quack/duck";
import { useT } from "@/lib/i18n/provider";
import { EASE_OUT, markPreloaderShown, shouldShowPreloader, usePrefersReducedMotion } from "@/lib/motion";
import { cn } from "@/lib/utils";
import type { Duck } from "./scanline/duck-3d";
import type { Scanline } from "./scanline/scanline";

/**
 * Прелоадер: тёмный полноэкранный оверлей с 3D-уткой в штриховке. Один раз за сессию вкладки.
 *
 * SSR и мигание: оверлей рендерится на сервере и на первом кадре клиента сразу (одинаково, без чтения
 * sessionStorage в рендере — гидратация не расходится), поэтому при первом заходе приложение не мелькает
 * под ним. Если прелоадер уже показан в этой вкладке, useLayoutEffect убирает его до первой отрисовки
 * клиента; цена — при повторной жёсткой перезагрузке тёмный оверлей виден на время загрузки JS.
 * Тяжёлое (three, канвас, утка) подгружается отдельными чанками — в основной бандл не попадает.
 */

// three и движок — отдельным чанком, только в браузере
const ScanlineCanvas = dynamic(() => import("./scanline/scanline-canvas").then((m) => m.ScanlineCanvas), {
  ssr: false,
});

const MIN_MS = 1800; // минимум показа (счёт 0→100)
const REDUCED_MS = 700; // то же при prefers-reduced-motion
const MAX_WAIT_MS = 3500; // дольше не ждём готовность (нет WebGL, шрифты зависли)
const HOLD_MS = 250; // пауза на 100%
const WIPE_MS = 1000; // шторка
const FADE_MS = 300; // затухание при reduced motion
const REDUCED_POSE_T = 0.3; // кадр утки без анимации: середина шага

const SCAN_OPTIONS = { step: 3, glitch: 0.3 };

// Холст 13:10 (утка шире, чем выше). Ширина min(max(52vmin,240px),520px), но не больше места в ячейке:
// 100cqw по ширине и 130cqh (= высота × 1.3) по высоте — так он никогда не налезает на нижние подписи.
// В портрете (телефон) ширина берётся от ячейки: 52vmin там слишком мало.
const CANVAS_CLASS =
  "block aspect-[13/10] w-[min(max(52vmin,240px),520px,100cqw,130cqh)] portrait:w-[min(92cqw,520px,130cqh)]";

type Phase = "show" | "exit" | "gone";
type DuckLib = typeof import("./scanline/duck-3d");

const easeOut = (k: number) => 1 - Math.pow(1 - k, 2.4);

export function Preloader() {
  const t = useT();
  const reduced = usePrefersReducedMotion();
  const [phase, setPhase] = useState<Phase>("show");
  const [percent, setPercent] = useState(0);
  const [lib, setLib] = useState<DuckLib | null>(null);

  const rootRef = useRef<HTMLDivElement>(null);
  const wordmarkRef = useRef<HTMLDivElement>(null);
  const decided = useRef<boolean | null>(null); // показывать ли: решаем один раз (StrictMode гоняет эффекты дважды)
  const ready = useRef({ fonts: false, frame: false });
  const libRef = useRef<DuckLib | null>(null);
  const duckRef = useRef<Duck | null>(null);
  const reducedRef = useRef(reduced);

  useEffect(() => {
    reducedRef.current = reduced;
  }, [reduced]);

  // уже показывали в этой вкладке — убираем до первой отрисовки
  useLayoutEffect(() => {
    decided.current ??= shouldShowPreloader();
    if (!decided.current) setPhase("gone");
  }, []);

  // загрузка утки и шрифтов = сигнал готовности
  useEffect(() => {
    if (decided.current === false) return;
    let alive = true;
    const fonts = typeof document !== "undefined" ? document.fonts : undefined;
    (fonts ? fonts.ready : Promise.resolve()).then(() => {
      if (alive) ready.current.fonts = true;
    });
    import("./scanline/duck-3d").then(
      (m) => {
        if (!alive) return;
        libRef.current = m;
        setLib(m);
      },
      () => {}, // чанк не загрузился: дождёмся таймаута и просто уйдём
    );
    return () => {
      alive = false;
    };
  }, []);

  // чистим утку, когда оверлей ушёл или компонент снят
  useEffect(() => {
    if (phase !== "gone") return;
    duckRef.current?.dispose();
    duckRef.current = null;
  }, [phase]);
  useEffect(
    () => () => {
      duckRef.current?.dispose();
      duckRef.current = null;
    },
    [],
  );

  // кадр штриховки: утка создаётся лениво, пока чанк не пришёл — пусто
  const onFrame = useCallback((s: Scanline, time: number) => {
    const l = libRef.current;
    if (!l) return;
    const duck = (duckRef.current ??= l.createDuck());
    const { width, height } = s.getSize();
    duck.update(reducedRef.current ? REDUCED_POSE_T : time, width / Math.max(1, height));
    s.renderScene(duck.scene, duck.camera, time);
    ready.current.frame = true;
  }, []);

  // новая ссылка на options после загрузки утки заставляет канвас перерисоваться (важно при reduced motion: там один кадр)
  const options = useMemo(() => ({ ...SCAN_OPTIONS }), [lib]); // eslint-disable-line react-hooks/exhaustive-deps

  // счётчик: easing за MIN_MS, на 99% ждёт готовности, потом пауза и выход
  useEffect(() => {
    if (phase !== "show" || decided.current === false) return;
    const dur = reduced ? REDUCED_MS : MIN_MS;
    const t0 = performance.now();
    let raf = 0;
    let hold = 0;
    let last = -1;
    const tick = (now: number) => {
      const el = now - t0;
      const k = Math.min(1, el / dur);
      const isReady = (ready.current.fonts && ready.current.frame) || el > MAX_WAIT_MS;
      let p = Math.round(easeOut(k) * 100);
      if (!isReady) p = Math.min(p, 99);
      if (p !== last) {
        last = p;
        setPercent(p);
      }
      if (k >= 1 && isReady) {
        hold = window.setTimeout(() => setPhase("exit"), HOLD_MS);
        return;
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(raf);
      window.clearTimeout(hold);
    };
  }, [phase, reduced]);

  // выход: шторка (или быстрое затухание), затем размонтирование
  useEffect(() => {
    if (phase !== "exit") return;
    markPreloaderShown();
    // затухание через WAAPI: глобальное правило reduced-motion обнуляет CSS-переходы
    if (reduced) rootRef.current?.animate?.([{ opacity: 1 }, { opacity: 0 }], { duration: FADE_MS, fill: "forwards" });
    const id = window.setTimeout(() => setPhase("gone"), (reduced ? FADE_MS : WIPE_MS) + 80);
    return () => window.clearTimeout(id);
  }, [phase, reduced]);

  // огромный логотип: подбираем кегль так, чтобы слово занимало всю ширину
  useLayoutEffect(() => {
    const wrap = wordmarkRef.current;
    const word = wrap?.firstElementChild as HTMLElement | null;
    if (!wrap || !word) return;
    let lastWidth = 0;
    const fit = () => {
      const width = wrap.clientWidth;
      if (width < 1) return;
      lastWidth = width;
      wrap.style.fontSize = "100px";
      const w100 = word.getBoundingClientRect().width;
      if (w100 > 0) wrap.style.fontSize = `${(width / w100) * 100 * 0.985}px`;
    };
    fit();
    const ro = new ResizeObserver(() => {
      if (wrap.clientWidth !== lastWidth) fit();
    });
    ro.observe(wrap);
    document.fonts?.ready.then(fit);
    return () => ro.disconnect();
  }, [phase]);

  if (phase === "gone") return null;

  const exiting = phase === "exit";
  const wipe = exiting && !reduced;

  return (
    <div
      ref={rootRef}
      inert={exiting}
      aria-busy={!exiting}
      className={cn(
        "fixed inset-0 z-[1000] overflow-hidden bg-cloth grain text-paper select-none",
        wipe && "mask-wipe animate-wipe-out",
        exiting && "pointer-events-none",
      )}
      style={wipe ? { animationDuration: `${WIPE_MS}ms`, animationTimingFunction: EASE_OUT } : undefined}
    >
      {/* содержимое чуть уезжает вверх, пока идёт шторка */}
      <div
        className="flex h-full flex-col"
        style={{
          transform: wipe ? "translateY(-6vh)" : undefined,
          transition: wipe ? `transform ${WIPE_MS}ms ${EASE_OUT}` : undefined,
        }}
      >
        <div className="flex min-h-0 flex-1 flex-col px-5 pt-5 sm:px-8 sm:pt-7">
          <div className="flex items-center gap-4" aria-hidden>
            <FlatDuck className="h-9 w-11" />
            <p className="caps [--caps-size:0.75rem]">
              {t.preloader.tagline1}
              <br />
              {t.preloader.tagline2}
            </p>
          </div>

          {/* свободное место между верхними подписями и нижними: контейнер даёт размеры в cqw/cqh, утка по ним не вылезает на подписи */}
          <div className="grid min-h-0 flex-1 place-items-center py-4 [container-type:size]">
            <ScanlineCanvas className={CANVAS_CLASS} options={options} onFrame={onFrame} />
          </div>

          <div className="flex items-end justify-between gap-6 pb-4 sm:pb-6">
            <p className="caps [--caps-size:0.75rem]" aria-hidden>
              {t.preloader.kindTop}
              <br />
              {t.preloader.kindBottom}
            </p>
            <div className="flex items-end gap-4 text-right">
              <p role="status" aria-live="polite" className="caps [--caps-size:0.75rem]">
                {t.preloader.loading}
                <br />
                <span className="text-paper-dim">{t.preloader.wait}</span>
              </p>
              <span aria-hidden className="num min-w-[4ch] text-3xl leading-none text-ribbon">
                {t.preloader.percent(percent)}
              </span>
            </div>
          </div>
        </div>

        {/* логотип на всю ширину, нижняя часть срезана краем экрана */}
        <div
          ref={wordmarkRef}
          aria-hidden
          className="relative h-[0.74em] w-full shrink-0 overflow-hidden text-center text-[22vw] leading-none"
        >
          <span className="text-striped display-caps inline-block whitespace-nowrap text-ribbon">QUACK!</span>
        </div>
      </div>
    </div>
  );
}
