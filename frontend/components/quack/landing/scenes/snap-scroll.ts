import { useEffect, type RefObject } from "react";
import { STORY, storyPos } from "./story";

/**
 * Прокрутка по точкам для закреплённых сцен. Человек начал крутить — сцена тут же рассыпается (прогресс идёт от самой
 * прокрутки). Крутит дальше и прошёл пятую часть пути — страница сама, плавно доезжает до следующей точки.
 * Остановился раньше — страница так же плавно возвращается, и сцена собирается обратно. После последней сцены прокрутка
 * свободная (подвал). Кнопки и ссылки просят страницу доехать через событие story-go.
 */
const THRESHOLD = 0.2; // доля пути до соседней точки, после которой страница едет сама
const IDLE_MS = 160; // столько тишины без прокрутки — решаем, куда вернуться
const FULL_SECONDS = 2.6; // сколько едет страница между соседними сценами: медленно, чтобы сцены плавно перетекали
const MIN_SECONDS = 0.9;
const COOLDOWN_MS = 800; // после остановки колесо и инерция тачпада не должны сразу запускать следующий переход

const easeInOut = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

export function useSnapScroll(scrollRef: RefObject<HTMLElement | null>, enabled: boolean) {
  useEffect(() => {
    const root = scrollRef.current;
    if (!root || !enabled) return;
    const P = STORY.points;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const nearest = (s: number) => P.reduce((best, p, i) => (Math.abs(p - s) < Math.abs(P[best] - s) ? i : best), 0);
    let cur = nearest(storyPos(root));
    let raf = 0;
    let animating = false;
    let idle = 0;
    let lockUntil = 0;
    // пока страница едет сама (и сразу после) колесо, тач и клавиши ничего не двигают: иначе их прокрутка дерётся с нашей
    const locked = () => animating || performance.now() < lockUntil;
    const block = (e: Event) => {
      if (locked() && e.cancelable) e.preventDefault();
    };

    const finish = () => {
      animating = false;
      lockUntil = performance.now() + COOLDOWN_MS;
    };
    const animateTo = (idx: number) => {
      cancelAnimationFrame(raf);
      cur = idx;
      const to = P[idx] * root.clientHeight;
      const from = root.scrollTop;
      if (Math.abs(to - from) < 2) return;
      if (reduced) {
        root.scrollTop = to;
        return;
      }
      animating = true;
      const t0 = performance.now();
      const dist = Math.abs(to - from) / root.clientHeight; // в высотах окна
      const dur = Math.max(MIN_SECONDS, Math.min(FULL_SECONDS, (FULL_SECONDS * dist) / 1.3)) * 1000;
      const step = (now: number) => {
        const k = Math.min(1, (now - t0) / dur);
        root.scrollTop = from + (to - from) * easeInOut(k);
        if (k < 1) raf = requestAnimationFrame(step);
        else finish();
      };
      raf = requestAnimationFrame(step);
    };

    const decide = (final: boolean) => {
      const s = storyPos(root);
      const a = P[cur];
      if (s > a + 0.01) {
        if (cur < P.length - 1) {
          const frac = (s - a) / (P[cur + 1] - a);
          if (frac >= THRESHOLD) animateTo(cur + 1);
          else if (final) animateTo(cur);
        } // после последней сцены прокрутка свободная
      } else if (s < a - 0.01) {
        if (cur > 0) {
          const frac = (a - s) / (a - P[cur - 1]);
          if (frac >= THRESHOLD) animateTo(cur - 1);
          else if (final) animateTo(cur);
        } else if (final) animateTo(cur);
      }
    };
    const onScroll = () => {
      if (locked()) return;
      decide(false);
      window.clearTimeout(idle);
      idle = window.setTimeout(() => !locked() && decide(true), IDLE_MS);
    };
    const onGo = (e: Event) => {
      const idx = (e as CustomEvent<number>).detail;
      if (typeof idx === "number") animateTo(Math.max(0, Math.min(P.length - 1, idx)));
    };
    root.addEventListener("scroll", onScroll, { passive: true });
    root.addEventListener("story-go", onGo);
    root.addEventListener("wheel", block, { passive: false });
    root.addEventListener("touchmove", block, { passive: false });
    return () => {
      cancelAnimationFrame(raf);
      window.clearTimeout(idle);
      root.removeEventListener("scroll", onScroll);
      root.removeEventListener("story-go", onGo);
      root.removeEventListener("wheel", block);
      root.removeEventListener("touchmove", block);
    };
  }, [scrollRef, enabled]);
}
