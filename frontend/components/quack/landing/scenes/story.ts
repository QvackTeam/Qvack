import { useSyncExternalStore } from "react";
import { smoothstep } from "./scene-utils";

/**
 * Закреплённые сцены. Первый экран и две сцены лежат друг на друге в одной неподвижной рамке (sticky), а прокрутка
 * не двигает страницу, а прокручивает «время»: графика одной сцены рассыпается на месте, и тут же из точек собирается
 * следующая. Время измеряется в высотах окна (s = scrollTop / высота окна).
 *
 *   s 0.04–0.55   первый экран рассыпается (его собственная логика)
 *   s 0.40–0.95   сцена «эффективность и память» собирается, до 1.65 стоит, до 2.15 рассыпается
 *   s 2.00–2.55   сцена «как работает» собирается и стоит до конца рамки
 */
export type Win = [number, number, number, number];

export const STORY = {
  efficiency: [0.4, 0.95, 1.65, 2.15] as Win,
  how: [2.0, 2.55, 99, 100] as Win,
  /** до какого s рамка остаётся на месте; дальше страница едет к подвалу */
  end: 3.2,
  /** куда прокручивать по якорным ссылкам (s) */
  anchors: { efficiency: 1.25, how: 2.9 } as Record<string, number>,
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

/** Якорная ссылка: в закреплённом режиме перематывает к нужному «времени», иначе обычный переход к секции */
export function goToScene(root: HTMLElement | null, id: string, e?: { preventDefault: () => void }) {
  if (!root) return;
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (root.dataset.pinned === "true" && id in STORY.anchors) {
    e?.preventDefault();
    root.scrollTo({ top: STORY.anchors[id] * root.clientHeight, behavior: reduced ? "auto" : "smooth" });
  } else if (id === "top") {
    e?.preventDefault();
    root.scrollTo({ top: 0, behavior: reduced ? "auto" : "smooth" });
  }
}

/** onClick для якорной ссылки вне страницы-контейнера (подвал, панель): находит контейнер сам */
export function onAnchor(id: string) {
  return (e: { preventDefault: () => void }) => goToScene(document.querySelector<HTMLElement>("main[data-pinned]"), id, e);
}
