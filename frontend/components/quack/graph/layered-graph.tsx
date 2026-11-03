"use client";

import { Maximize2, Minus, Plus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
import { layoutGraph, loadPositions, savePositions } from "@/lib/graph/layout";
import { onGraph, type GraphModel, type GraphTopic } from "@/lib/graph/types";
import { useT } from "@/lib/i18n/provider";
import type { Domain, TopicState } from "@/lib/mock/types";
import { IconButton } from "../icon-button";
import { StateDot, TopicCardBody } from "../topic-card";

export type GraphHandle = { focusTopic: (id: string) => void };

type View = { k: number; tx: number; ty: number };
type Pt = { x: number; y: number };
type Colors = Record<"paper" | "dim" | "ribbon" | "cloth" | TopicState, string> & { label: string; body: string };

const K_MIN = 0.04;
const K_MAX = 2.4;
const FIT_K_MAX = 1.2;
const FIT_MARGIN = 56;
const TWEEN_MS = 450;
const CARD_W = 320;
/** The learner id is unknown on mocks; the key only has to be stable on this device */
const LEARNER = "local";

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
const easeOut = (t: number) => 1 - Math.pow(1 - t, 4);
const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** Canvas cannot use CSS classes, so colours and fonts are read once from probe elements */
function readColors(host: HTMLElement): Colors {
  const probe = (cls: string, prop: "color" | "fontFamily") => {
    const el = document.createElement("span");
    el.className = cls;
    el.style.cssText = "position:absolute;visibility:hidden";
    host.appendChild(el);
    const v = getComputedStyle(el)[prop];
    el.remove();
    return v;
  };
  return {
    paper: probe("text-paper", "color"),
    dim: probe("text-paper-dim", "color"),
    ribbon: probe("text-ribbon", "color"),
    cloth: probe("text-cloth", "color"),
    solid: probe("text-st-solid", "color"),
    review: probe("text-st-review", "color"),
    confused: probe("text-st-confused", "color"),
    new: probe("text-st-new", "color"),
    label: probe("font-label", "fontFamily"),
    body: probe("font-sans", "fontFamily"),
  };
}

const WEAK = new Set(["confused_with", "persistent_error", "struggling", "inconsistent"]);

/** Topic state for colour and legend. Stage 6 gives indicators their own palette */
function stateOf(t: GraphTopic, nowMs: number): TopicState {
  if (t.status === "proposed" || !t.displayState || t.displayState === "not_tested") return "new";
  if (WEAK.has(t.displayState)) return "confused";
  if (t.nearestDueAtMs !== undefined && t.nearestDueAtMs <= nowMs) return "review";
  return "solid";
}

export const LayeredGraph = forwardRef<GraphHandle, { model: GraphModel; domain: Domain }>(function LayeredGraph({ model, domain }, ref) {
  const tx = useT();
  const router = useRouter();
  const wrap = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [hover, setHover] = useState<{ id: string; x: number; y: number } | null>(null);

  // The draw loop reads refs, so panning does not re-render React
  const view = useRef<View>({ k: 1, tx: 0, ty: 0 });
  const shown = useRef(new Map<string, Pt>());
  const from = useRef(new Map<string, Pt>());
  const target = useRef(new Map<string, Pt>());
  const posTween = useRef<number | null>(null);
  const viewTween = useRef<{ start: number; from: View; to: View } | null>(null);
  const raf = useRef(0);
  const loop = useRef<FrameRequestCallback>(() => {});
  const colors = useRef<Colors | null>(null);
  const hoverKey = useRef<string | null>(null);
  const drag = useRef<{ x: number; y: number; vx: number; vy: number; moved: boolean } | null>(null);
  const hideTimer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const fitted = useRef(false);
  const sizeRef = useRef(size);

  const topicMap = useMemo(() => new Map(model.topics.map((t) => [t.id, t])), [model]);
  const hubMap = useMemo(() => new Map(model.hubs.map((h) => [h.id, h])), [model]);
  // Saved positions keep known topics in place. The node list does not depend on them, so server and client markup match
  const layout = useMemo(() => layoutGraph(model, loadPositions(LEARNER, model.domainId)), [model]);
  const scene = useRef({ layout, model, topicMap, hubMap });

  const draw = useCallback(() => {
    const c = canvas.current;
    const col = colors.current;
    const { w, h } = sizeRef.current;
    if (!c || !col || !w || !h) return;
    const ctx = c.getContext("2d");
    if (!ctx) return;
    const { layout: L, model: m, topicMap: topics, hubMap: hubs } = scene.current;
    const dpr = window.devicePixelRatio || 1;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    const { k, tx: vx, ty: vy } = view.current;
    const pos = (key: string) => shown.current.get(key);
    const sx = (x: number) => x * k + vx;
    const sy = (y: number) => y * k + vy;
    const near = (x: number, y: number, pad: number) => x > -pad && x < w + pad && y > -pad && y < h + pad;
    const hovered = hoverKey.current;

    // Topic to hub: soft, see-through lines. Stage 3 turns them into bundles
    ctx.lineWidth = 1;
    ctx.strokeStyle = col.ribbon;
    ctx.globalAlpha = 0.1;
    ctx.beginPath();
    for (const l of m.includes) {
      const a = pos(l.topicId);
      const b = pos(`h:${l.hubId}`);
      if (!a || !b) continue;
      const ax = sx(a.x), ay = sy(a.y), bx = sx(b.x), by = sy(b.y);
      if (!near(ax, ay, 400) && !near(bx, by, 400)) continue;
      ctx.moveTo(ax, ay);
      ctx.quadraticCurveTo(ax, by + (ay - by) * 0.35, bx, by);
    }
    ctx.stroke();

    // Topic to topic: straight and solid, from the prerequisite up to the topic that needs it
    const edges = m.requires.filter((e) => L.nodes.has(e.topicId) && L.nodes.has(e.requiresId));
    const line = (keep: (a: string, b: string) => boolean) => {
      ctx.beginPath();
      for (const e of edges) {
        if (!keep(e.topicId, e.requiresId)) continue;
        const a = pos(e.requiresId);
        const b = pos(e.topicId);
        if (!a || !b) continue;
        const ax = sx(a.x), ay = sy(a.y), bx = sx(b.x), by = sy(b.y);
        if ((ax < 0 && bx < 0) || (ax > w && bx > w) || (ay < 0 && by < 0) || (ay > h && by > h)) continue;
        ctx.moveTo(ax, ay);
        ctx.lineTo(bx, by);
      }
      ctx.stroke();
    };
    ctx.strokeStyle = col.dim;
    ctx.globalAlpha = 0.4;
    line(() => true);
    if (hovered && !hovered.startsWith("h:")) {
      ctx.strokeStyle = col.paper;
      ctx.globalAlpha = 0.85;
      line((a, b) => a === hovered || b === hovered);
    }
    ctx.globalAlpha = 1;

    // Topics
    const rT = clamp(7 * Math.pow(k, 0.7), 2.5, 8.5);
    for (const n of L.topics) {
      const p = pos(n.key);
      const t = topics.get(n.id);
      if (!p || !t) continue;
      const x = sx(p.x), y = sy(p.y);
      if (!near(x, y, 20)) continue;
      const st = stateOf(t, m.nowMs);
      const hollow = st === "new";
      ctx.globalAlpha = t.status === "proposed" ? 0.6 : 1;
      ctx.beginPath();
      ctx.arc(x, y, n.key === hovered ? rT + 2 : rT, 0, Math.PI * 2);
      if (hollow) {
        ctx.fillStyle = col.cloth;
        ctx.fill();
        ctx.lineWidth = 1.6;
        ctx.strokeStyle = col.new;
        ctx.stroke();
      } else {
        ctx.fillStyle = col[st];
        ctx.fill();
      }
    }
    ctx.globalAlpha = 1;

    // Hubs: bigger than topics, ring with a dot. Deadline hubs look the same as the others
    const rH = clamp(13 * Math.pow(k, 0.6), 5, 15);
    for (const n of L.hubs) {
      const p = pos(n.key);
      if (!p) continue;
      const x = sx(p.x), y = sy(p.y);
      if (!near(x, y, 40)) continue;
      const r = n.key === hovered ? rH + 2 : rH;
      ctx.beginPath();
      ctx.arc(x, y, r, 0, Math.PI * 2);
      ctx.fillStyle = col.cloth;
      ctx.fill();
      ctx.lineWidth = 2;
      ctx.strokeStyle = col.ribbon;
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(x, y, r * 0.38, 0, Math.PI * 2);
      ctx.fillStyle = col.ribbon;
      ctx.fill();
    }

    // Labels. Stage 4 replaces this with levels of detail and collision handling
    ctx.textAlign = "center";
    ctx.lineJoin = "round";
    ctx.font = `500 12px ${col.label}`;
    ctx.textBaseline = "bottom";
    for (const n of L.hubs) {
      const p = pos(n.key);
      if (!p) continue;
      const x = sx(p.x), y = sy(p.y);
      if (!near(x, y, 80)) continue;
      const text = (hubs.get(n.id)?.name ?? "").toUpperCase();
      ctx.lineWidth = 4;
      ctx.strokeStyle = col.cloth;
      ctx.strokeText(text, x, y - rH - 5);
      ctx.fillStyle = col.paper;
      ctx.fillText(text, x, y - rH - 5);
    }
    if (k >= 0.55) {
      ctx.font = `400 11px ${col.body}`;
      ctx.textBaseline = "top";
      for (const n of L.topics) {
        const p = pos(n.key);
        const t = topics.get(n.id);
        if (!p || !t) continue;
        const x = sx(p.x), y = sy(p.y);
        if (!near(x, y, 80)) continue;
        ctx.lineWidth = 3;
        ctx.strokeStyle = col.cloth;
        ctx.strokeText(t.name, x, y + rT + 4);
        ctx.fillStyle = col.dim;
        ctx.fillText(t.name, x, y + rT + 4);
      }
    }
  }, []);

  const frame = useCallback(
    (now: number) => {
      raf.current = 0;
      let again = false;
      if (posTween.current !== null) {
        const t = clamp((now - posTween.current) / TWEEN_MS, 0, 1);
        const e = easeOut(t);
        for (const [key, to] of target.current) {
          const f = from.current.get(key) ?? to;
          shown.current.set(key, { x: f.x + (to.x - f.x) * e, y: f.y + (to.y - f.y) * e });
        }
        if (t >= 1) posTween.current = null;
        else again = true;
      }
      const vt = viewTween.current;
      if (vt) {
        const t = clamp((now - vt.start) / TWEEN_MS, 0, 1);
        const e = easeOut(t);
        view.current = { k: vt.from.k + (vt.to.k - vt.from.k) * e, tx: vt.from.tx + (vt.to.tx - vt.from.tx) * e, ty: vt.from.ty + (vt.to.ty - vt.from.ty) * e };
        if (t >= 1) viewTween.current = null;
        else again = true;
      }
      draw();
      if (again) raf.current = requestAnimationFrame(loop.current);
    },
    [draw],
  );

  useEffect(() => {
    loop.current = frame;
  }, [frame]);

  const schedule = useCallback(() => {
    if (!raf.current) raf.current = requestAnimationFrame(loop.current);
  }, []);

  const moveView = useCallback(
    (to: View, animate: boolean) => {
      if (animate && !reducedMotion()) viewTween.current = { start: performance.now(), from: view.current, to };
      else {
        viewTween.current = null;
        view.current = to;
      }
      schedule();
    },
    [schedule],
  );

  const fitView = useCallback((w: number, h: number): View => {
    const { x0, x1, y0, y1 } = scene.current.layout.bounds;
    const k = clamp(Math.min((w - FIT_MARGIN * 2) / Math.max(1, x1 - x0), (h - FIT_MARGIN * 2) / Math.max(1, y1 - y0)), K_MIN, FIT_K_MAX);
    return { k, tx: w / 2 - ((x0 + x1) / 2) * k, ty: h / 2 - ((y0 + y1) / 2) * k };
  }, []);

  const zoomAt = useCallback(
    (cx: number, cy: number, factor: number) => {
      const v = viewTween.current?.to ?? view.current;
      const k = clamp(v.k * factor, K_MIN, K_MAX);
      const f = k / v.k;
      moveView({ k, tx: cx - (cx - v.tx) * f, ty: cy - (cy - v.ty) * f }, false);
    },
    [moveView],
  );

  const fitAll = useCallback(() => moveView(fitView(sizeRef.current.w, sizeRef.current.h), true), [fitView, moveView]);

  // Colours and size
  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    colors.current = readColors(el);
    const ro = new ResizeObserver(() => {
      const r = el.getBoundingClientRect();
      setSize({ w: Math.round(r.width), h: Math.round(r.height) });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    sizeRef.current = size;
    const c = canvas.current;
    if (c && size.w && size.h) {
      const dpr = window.devicePixelRatio || 1;
      c.width = Math.round(size.w * dpr);
      c.height = Math.round(size.h * dpr);
      // Until stage 5 stores the camera, the first view is the whole graph
      if (!fitted.current) {
        fitted.current = true;
        view.current = fitView(size.w, size.h);
      }
    }
    schedule();
  }, [size, fitView, schedule]);

  // A new layout: known nodes stay, whatever moved glides to its place
  useEffect(() => {
    scene.current = { layout, model, topicMap, hubMap };
    savePositions(LEARNER, model.domainId, layout);
    const first = shown.current.size === 0;
    from.current = new Map(shown.current);
    target.current = new Map([...layout.nodes.values()].map((n) => [n.key, { x: n.x, y: n.y }]));
    // A new node appears where it belongs, it does not fly in from the corner
    for (const [key, to] of target.current) if (!from.current.has(key)) from.current.set(key, to);
    if (first || reducedMotion()) {
      shown.current = new Map(target.current);
      posTween.current = null;
    } else posTween.current = performance.now();
    schedule();
  }, [layout, model, topicMap, hubMap, schedule]);

  // Strict Mode runs this cleanup once in development: forget the cancelled frame so the loop can restart
  useEffect(
    () => () => {
      cancelAnimationFrame(raf.current);
      raf.current = 0;
    },
    [],
  );

  // A wheel handler must be non-passive to stop the page from scrolling
  useEffect(() => {
    const el = canvas.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const r = el.getBoundingClientRect();
      zoomAt(e.clientX - r.left, e.clientY - r.top, Math.exp(-e.deltaY * (e.ctrlKey ? 0.01 : 0.0016)));
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [zoomAt]);

  const hitTest = (px: number, py: number): string | null => {
    const { k, tx: vx, ty: vy } = view.current;
    const rT = clamp(7 * Math.pow(k, 0.7), 2.5, 8.5) + 6;
    const rH = clamp(13 * Math.pow(k, 0.6), 5, 15) + 6;
    let best: string | null = null;
    let bestD = Infinity;
    for (const n of [...layout.hubs, ...layout.topics]) {
      const p = shown.current.get(n.key);
      if (!p) continue;
      const d = Math.hypot(p.x * k + vx - px, p.y * k + vy - py);
      if (d <= (n.kind === "hub" ? rH : rT) && d < bestD) {
        best = n.key;
        bestD = d;
      }
    }
    return best;
  };

  const setHoverKey = (key: string | null, px = 0, py = 0) => {
    if (hoverKey.current === key) return;
    hoverKey.current = key;
    schedule();
    clearTimeout(hideTimer.current);
    if (key && !key.startsWith("h:")) setHover({ id: key, x: px, y: py });
    else if (key) setHover(null);
    else hideTimer.current = setTimeout(() => setHover(null), 220);
  };

  const local = (e: React.PointerEvent) => {
    const r = canvas.current!.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
  };

  const onPointerDown = (e: React.PointerEvent) => {
    if (e.button !== 0) return;
    const p = local(e);
    viewTween.current = null;
    drag.current = { x: p.x, y: p.y, vx: view.current.tx, vy: view.current.ty, moved: false };
    canvas.current!.setPointerCapture(e.pointerId);
  };

  const onPointerMove = (e: React.PointerEvent) => {
    const p = local(e);
    const d = drag.current;
    if (d) {
      if (!d.moved && Math.hypot(p.x - d.x, p.y - d.y) > 4) {
        d.moved = true;
        setHoverKey(null);
        setHover(null);
      }
      if (d.moved) {
        view.current = { ...view.current, tx: d.vx + p.x - d.x, ty: d.vy + p.y - d.y };
        schedule();
      }
      return;
    }
    if (e.pointerType === "touch") return;
    const key = hitTest(p.x, p.y);
    setHoverKey(key, p.x, p.y);
    canvas.current!.style.cursor = key ? "pointer" : "grab";
  };

  const onPointerUp = (e: React.PointerEvent) => {
    const d = drag.current;
    drag.current = null;
    if (canvas.current?.hasPointerCapture(e.pointerId)) canvas.current.releasePointerCapture(e.pointerId);
    if (!d || d.moved) return;
    const p = local(e);
    const key = hitTest(p.x, p.y);
    if (key) router.push(key.startsWith("h:") ? `/hub/${key.slice(2)}` : `/topic/${key}`);
  };

  const focusTopic = useCallback(
    (id: string) => {
      const p = target.current.get(id);
      if (!p) return;
      const { w, h } = sizeRef.current;
      const k = clamp(Math.max(view.current.k, 0.9), K_MIN, K_MAX);
      moveView({ k, tx: w / 2 - p.x * k, ty: h / 2 - p.y * k }, true);
      hoverKey.current = id;
      setHover({ id, x: w / 2, y: h / 2 });
    },
    [moveView],
  );
  useImperativeHandle(ref, () => ({ focusTopic }), [focusTopic]);

  const hoverTopic = hover ? topicMap.get(hover.id) : undefined;
  const hoverMock = hover ? domain.topics.find((t) => t.id === hover.id) : undefined;
  const hubCount = model.hubs.filter((h) => h.kind !== "domain_all").length;
  const topicCount = model.topics.filter(onGraph).length;
  const allHub = model.hubs.find((h) => h.kind === "domain_all");

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="@container flex min-h-10 shrink-0 flex-wrap items-center gap-x-6 border-b border-seam-soft text-paper-dim">
        <p aria-live="polite" className="caps shrink-0">
          {tx.graph.status(hubCount, topicCount)}
        </p>
        <ul className="order-last flex basis-full flex-wrap items-center gap-x-4 pb-2 @[40rem]:order-none @[40rem]:min-w-0 @[40rem]:flex-1 @[40rem]:basis-auto @[40rem]:pb-0" aria-label={tx.graph.statesLabel}>
          {(["solid", "review", "confused", "new"] as const).map((s) => (
            <li key={s} className="caps flex items-center gap-2 whitespace-nowrap">
              <StateDot state={s} />
              {tx.states[s].toLowerCase()}
            </li>
          ))}
        </ul>
        <div className="ml-auto flex shrink-0 items-center">
          {allHub && (
            <Link
              href={`/hub/${allHub.id}`}
              aria-label={tx.graph.allTopicsPillAria}
              className="caps mr-1 inline-flex h-10 shrink-0 items-center rounded-pill border border-seam px-4 whitespace-nowrap text-paper transition-colors duration-(--dur-s) ease-(--ease-out) hover:border-rule hover:bg-cloth-hover"
            >
              {tx.graph.allTopicsPill}
            </Link>
          )}
          <div className="flex" role="group" aria-label={tx.graph.zoomGroup}>
            <IconButton label={tx.graph.zoomIn} onClick={() => zoomAt(size.w / 2, size.h / 2, 1.25)}>
              <Plus />
            </IconButton>
            <IconButton label={tx.graph.zoomOut} onClick={() => zoomAt(size.w / 2, size.h / 2, 0.8)}>
              <Minus />
            </IconButton>
            <IconButton label={tx.graph.fitAll} onClick={fitAll}>
              <Maximize2 />
            </IconButton>
          </div>
        </div>
      </div>

      <div
        ref={wrap}
        tabIndex={0}
        role="application"
        aria-label={tx.graph.ariaGraph(domain.title)}
        className="relative min-h-0 flex-1 overflow-hidden rounded-[2px] outline-none select-none focus-visible:ring-2 focus-visible:ring-ribbon/60"
        onKeyDown={(e) => {
          if (e.target !== e.currentTarget) return;
          const pan = (dx: number, dy: number) => moveView({ ...view.current, tx: view.current.tx + dx, ty: view.current.ty + dy }, false);
          const map: Record<string, () => void> = {
            ArrowLeft: () => pan(60, 0),
            ArrowRight: () => pan(-60, 0),
            ArrowUp: () => pan(0, 60),
            ArrowDown: () => pan(0, -60),
            "+": () => zoomAt(size.w / 2, size.h / 2, 1.25),
            "=": () => zoomAt(size.w / 2, size.h / 2, 1.25),
            "-": () => zoomAt(size.w / 2, size.h / 2, 0.8),
            "0": fitAll,
          };
          const fn = map[e.key];
          if (fn) {
            e.preventDefault();
            fn();
          }
        }}
      >
        <canvas
          ref={canvas}
          className="absolute inset-0 cursor-grab touch-none"
          style={{ width: size.w, height: size.h }}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={onPointerUp}
          onPointerLeave={() => !drag.current && setHoverKey(null)}
        />

        {/* Real links for keyboard and screen readers. Small graphs only: 500 tab stops would be worse than none */}
        {layout.nodes.size <= 150 && (
          <ul className="sr-only">
            {layout.hubs.map((n) => (
              <li key={n.key}>
                <Link href={`/hub/${n.id}`}>{hubMap.get(n.id)?.name}</Link>
              </li>
            ))}
            {layout.topics.map((n) => (
              <li key={n.key}>
                <Link href={`/topic/${n.id}`}>{topicMap.get(n.id)?.name}</Link>
              </li>
            ))}
          </ul>
        )}

        {hover && hoverTopic && (
          <div
            data-card
            onPointerEnter={() => clearTimeout(hideTimer.current)}
            onPointerLeave={() => {
              hoverKey.current = null;
              hideTimer.current = setTimeout(() => setHover(null), 220);
            }}
            className="absolute z-10 rounded-[2px] border border-seam bg-cloth-raised p-4 shadow-[0_12px_32px_-12px_rgb(0_0_0/0.7)]"
            style={{
              width: CARD_W,
              left: hover.x + 18 + CARD_W < size.w ? hover.x + 18 : Math.max(8, hover.x - 18 - CARD_W),
              top: clamp(hover.y - 36, 8, Math.max(8, size.h - 280)),
            }}
          >
            {hoverMock ? (
              <TopicCardBody topic={hoverMock} hubLabel={domain.hubs.find((h) => h.id === hoverMock.hubId)?.title} />
            ) : (
              <>
                <h3 className="display-caps text-[1.0625rem]">
                  <Link href={`/topic/${hoverTopic.id}`} className="text-paper underline decoration-seam decoration-1 underline-offset-4 hover:decoration-rule">
                    {hoverTopic.name}
                  </Link>
                </h3>
                <p className="caps mt-3 flex items-center gap-2 text-paper">
                  <StateDot state={stateOf(hoverTopic, model.nowMs)} />
                  {tx.states[stateOf(hoverTopic, model.nowMs)]}
                </p>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
});
