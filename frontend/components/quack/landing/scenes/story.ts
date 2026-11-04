import { useSyncExternalStore } from "react";
import { smoothstep } from "./scene-utils";

/**
 * Закреплённые сцены. Первый экран и две сцены лежат друг на друге в одной неподвижной рамке (sticky), а прокрутка
 * не двигает страницу, а прокручивает «время»: графика одной сцены рассыпается на месте, и тут же из точек собирается
 * следующая. Время измеряется в высотах окна (s = scrollTop / высота окна).
 *
 *   s 0.04–0.55   первый экран рассыпается (его собственная логика)
 *   s 0.30–0.95   сцена «эффективность и память» собирается, стоит до 1.32, рассыпается к 1.9
 *   s 1.70–2.40   сцена «как работает» собирается и стоит до конца рамки
 *
 * Точки остановок — s = 0, 1.25, 2.55: сцена полностью собрана. Начал крутить — сцена тут же начинает рассыпаться, а если
 * крутить дальше, страница сама доезжает до следующей точки (см. snap-scroll.ts).
 */
export type Win = [number, number, number, number];

export const STORY = {
  efficiency: [0.3, 0.95, 1.32, 1.9] as Win,
  how: [1.7, 2.4, 99, 100] as Win,
  /** до какого s рамка остаётся на месте; дальше страница едет к подвалу */
  end: 2.7,
  /** точки остановок (s) и номера сцен по якорям */
  points: [0, 1.25, 2.55],
  anchors: { top: 0, efficiency: 1, how: 2 } as Record<string, number>,
};

/** Закреплённый режим включается на достаточно большом экране; на телефоне — обычная прокрутка со сценами друг под другом */
const QUERY = "(min-width: 1024px) and (min-height: 640px)";
export function usePinned(): boolean {
  return useSyncExternalStore(
    (cb) => {
      const mq = window.matchMedia(QUERY);
      mq.addEventListener("change", cb);
      return () => mq.removeEventListener("change", cb);
    },
    () => window.matchMedia(QUERY).matches,
    () => false,
  );
}

/** Положение прокрутки в высотах окна */
export function storyPos(root: HTMLElement): number {
  return root.scrollTop / Math.max(1, root.clientHeight);
}

/** Собранность сцены 0..1 по окну времени */
export function storyForm(root: HTMLElement, w: Win): number {
  const s = storyPos(root);
  return smoothstep(w[0], w[1], s) * (1 - smoothstep(w[2], w[3], s));
}

/** Сцена хоть чуть видна (с запасом) */
export function storyVisible(root: HTMLElement, w: Win, margin = 0.08): boolean {
  const s = storyPos(root);
  return s > w[0] - margin && s < w[3] + margin;
}

/** Якорная ссылка: в закреплённом режиме просит страницу доехать до нужной точки (её ведёт snap-scroll), иначе обычный переход к секции */
export function goToScene(root: HTMLElement | null, id: string, e?: { preventDefault: () => void }) {
  if (!root) return;
  if (root.dataset.pinned === "true" && id in STORY.anchors) {
    e?.preventDefault();
    root.dispatchEvent(new CustomEvent("story-go", { detail: STORY.anchors[id] }));
  } else if (id === "top") {
    e?.preventDefault();
    root.scrollTo({ top: 0, behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  }
}

/** onClick для якорной ссылки вне страницы-контейнера (подвал, панель): находит контейнер сам */
export function onAnchor(id: string) {
  return (e: { preventDefault: () => void }) => goToScene(document.querySelector<HTMLElement>("main[data-pinned]"), id, e);
}
