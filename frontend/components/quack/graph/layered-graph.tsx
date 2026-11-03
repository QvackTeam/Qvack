"use client";

import { Maximize2, Minus, Plus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
import { GAP_X, GAP_Y, layoutGraph, loadPositions, savePositions } from "@/lib/graph/layout";
import { onGraph, type GraphModel, type GraphTopic } from "@/lib/graph/types";
import { enterDomain, LEARNER, leaveDomain, saveAllVisits, updateDomain } from "@/lib/graph/visit-store";
import { loadCamera, restoreCenter, saveCamera, type SavedCamera } from "@/lib/graph/visit";
import { useT } from "@/lib/i18n/provider";
import type { Domain, TopicState } from "@/lib/mock/types";
import { IconButton } from "../icon-button";
import { StateDot, TopicCardBody } from "../topic-card";

export type GraphHandle = { focusTopic: (id: string) => void };

type View = { k: number; tx: number; ty: number };
type Pt = { x: number; y: number };
type Colors = Record<"paper" | "dim" | "ribbon" | "cloth" | TopicState, string> & { label: string; body: string; ribbonRgb: string };

const K_MIN = 0.04;
const K_MAX = 2.4;
const FIT_K_MAX = 1.2;
const FIT_MARGIN = 56;
const TWEEN_MS = 450;
/** A topic leaving the column for its place on the graph travels slower: the learner should see where it went */
const MOVE_MS = 900;
/** Width of the left column. It is fixed on screen, so the labels stay readable at any zoom */
const COL_W = 208;
const CARD_W = 320;
/** How long a changed node pulses */
const FLASH_MS = 1800;

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
const easeOut = (t: number) => 1 - Math.pow(1 - t, 4);
const smooth = (a: number, b: number, v: number) => {
  const t = clamp((v - a) / (b - a), 0, 1);
  return t * t * (3 - 2 * t);
};
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
  // Gradient stops need a colour with alpha; whatever CSS gave us is turned into plain r, g, b once
  const rgb = (css: string) => {
    const px = document.createElement("canvas");
    px.width = px.height = 1;
    const c = px.getContext("2d");
    if (!c) return "168,148,116";
    c.fillStyle = css;
    c.fillRect(0, 0, 1, 1);
    const d = c.getImageData(0, 0, 1, 1).data;
    return `${d[0]},${d[1]},${d[2]}`;
  };
  const ribbon = probe("text-ribbon", "color");
  return {
    ribbonRgb: rgb(ribbon),
    paper: probe("text-paper", "color"),
    dim: probe("text-paper-dim", "color"),
    ribbon,
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

export const LayeredGraph = forwardRef<GraphHandle, { model: GraphModel; domain: Domain; highlight?: { topicIds: string[]; hubIds: string[] } }>(function LayeredGraph({ model, domain, highlight }, ref) {
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
  const posMs = useRef(TWEEN_MS);
  // Labels fade in and out on their own clock, so a label never blinks when the zoom or a collision changes its fate
  const labelVis = useRef(new Map<string, number>());
  const textW = useRef(new Map<string, number>());
  const lastDraw = useRef(0);
  const flash = useRef(new Map<string, number>());
  const lit = useRef<string[]>([]);
  const camTimer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const colY = useRef(new Map<string, number>());
  const colEls = useRef(new Map<string, HTMLElement>());
  const colScroll = useRef<HTMLElement | null>(null);
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
  // Left column: unlinked topics of this domain, then topics from other subjects
  const column = useMemo(() => {
    const free = layout.unlinked.map((id) => topicMap.get(id)).filter((t): t is GraphTopic => !!t);
    const outside = [
      ...model.otherDomain.map((o) => ({ topic: o.topic, domainName: o.domainName as string | undefined })),
      ...model.topics.filter((t) => t.status === "off_domain" && t.visibility !== "hidden").map((t) => ({ topic: t, domainName: undefined })),
    ];
    return { free, outside, width: free.length || outside.length ? COL_W : 0 };
  }, [layout, topicMap, model]);
  const lookup = useMemo(() => new Map([...topicMap, ...model.otherDomain.map((o): [string, GraphTopic] => [o.topic.id, o.topic])]), [topicMap, model]);
  const links = useMemo(() => {
    const byHub = new Map<string, string[]>();
    const hubsOf = new Map<string, string[]>();
    for (const l of model.includes) {
      byHub.set(l.hubId, [...(byHub.get(l.hubId) ?? []), l.topicId]);
      hubsOf.set(l.topicId, [...(hubsOf.get(l.topicId) ?? []), l.hubId]);
    }
    const edges = model.requires.filter((e) => layout.nodes.has(e.topicId) && layout.nodes.has(e.requiresId));
    // Topics with more links are more important when two labels fight for the same place
    const degree = new Map<string, number>();
    for (const e of edges) {
      degree.set(e.topicId, (degree.get(e.topicId) ?? 0) + 1);
      degree.set(e.requiresId, (degree.get(e.requiresId) ?? 0) + 1);
    }
    return { byHub, hubsOf, edges, degree };
  }, [model, layout]);
  const scene = useRef({ layout, model, topicMap, hubMap, colW: column.width, links });

  const draw = useCallback((): boolean => {
    const c = canvas.current;
    const col = colors.current;
    const { w, h } = sizeRef.current;
    if (!c || !col || !w || !h) return false;
    const ctx = c.getContext("2d");
    if (!ctx) return false;
    const { layout: L, model: m, topicMap: topics, hubMap: hubs, colW, links } = scene.current;
    const dpr = window.devicePixelRatio || 1;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    const { k, tx: vx, ty: vy } = view.current;
    const pos = (key: string) => shown.current.get(key);
    const sx = (x: number) => x * k + vx;
    const sy = (y: number) => y * k + vy;
    const near = (x: number, y: number, pad: number) => x > -pad && x < w + pad && y > -pad && y < h + pad;
    const hovered = hoverKey.current;

    // Topic to hub: soft, see-through curves. They are brighter the closer the topic is to the hub, dimmer at the foot.
    // Close to the hub they gather into one brighter stem. Hovering a hub lights its lines and mutes the rest;
    // hovering a topic lights its curves to its hubs.
    const hoverHub = hovered?.startsWith("h:") ? hovered.slice(2) : null;
    const hoverTopic = hovered && !hovered.startsWith("h:") ? hovered : null;
    const litHubs = new Set(hoverTopic ? (links.hubsOf.get(hoverTopic) ?? []) : []);
    const ringR = clamp(13 * Math.pow(k, 0.6), 5, 15);
    ctx.lineWidth = 1.2;
    for (const [hubId, members] of links.byHub) {
      const hp = pos(`h:${hubId}`);
      if (!hp) continue;
      const hx = sx(hp.x), hy = sy(hp.y);
      const lit = hoverHub === hubId;
      const mute = hoverHub !== null && !lit;
      // The foot of the stem sits below the hub on screen; the curves end there
      const sxp = hx, syp = hy + Math.max(ringR + 6, 0.5 * GAP_Y * k);
      let any = false;
      for (const topicId of members) {
        const a = pos(topicId);
        const cy = colY.current.get(topicId);
        const ax = a ? sx(a.x) : colW, ay = a ? sy(a.y) : cy;
        if (ay === undefined || (!a && !colW)) continue;
        if (!near(ax, ay, 300) && !near(hx, hy, 300)) continue;
        any = true;
        const dist = Math.max(0, ay - hy) / Math.max(k, 1e-6) / GAP_Y; // in layers
        const close = Math.exp(-dist / 4);
        let alpha = 0.06 + 0.24 * close;
        if (lit) alpha = 0.5 + 0.3 * close;
        else if (hoverTopic === topicId) alpha = 0.85;
        if (mute) alpha *= 0.3;
        const mid = (ay + syp) / 2;
        const g = ctx.createLinearGradient(0, ay, 0, syp);
        g.addColorStop(0, `rgba(${col.ribbonRgb},${(alpha * 0.3).toFixed(3)})`);
        g.addColorStop(1, `rgba(${col.ribbonRgb},${alpha.toFixed(3)})`);
        ctx.strokeStyle = g;
        ctx.beginPath();
        ctx.moveTo(ax, ay);
        ctx.bezierCurveTo(ax, mid, sxp, mid, sxp, syp);
        ctx.stroke();
      }
      if (any) {
        ctx.strokeStyle = col.ribbon;
        ctx.globalAlpha = (lit || litHubs.has(hubId) ? 0.9 : 0.38) * (mute ? 0.3 : 1);
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(hx, hy + ringR);
        ctx.lineTo(sxp, syp);
        ctx.stroke();
        ctx.globalAlpha = 1;
        ctx.lineWidth = 1.2;
      }
    }

    // Topic to topic: straight and solid, from the prerequisite up to the topic that needs it
    const edges = links.edges;
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
    ctx.globalAlpha = 0.6;
    ctx.lineWidth = 1.4;
    line(() => true);
    if (hovered && !hovered.startsWith("h:")) {
      ctx.strokeStyle = col.paper;
      ctx.globalAlpha = 0.95;
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
      const r = n.key === hovered || litHubs.has(n.id) ? rH + 2 : rH;
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

    // The topic or hub of the "Today" card under the pointer
    if (lit.current.length) {
      for (const key of lit.current) {
        const p = pos(key);
        if (!p) continue;
        const x = sx(p.x), y = sy(p.y);
        const r0 = (key.startsWith("h:") ? rH : rT) + 7;
        ctx.globalAlpha = 0.18;
        ctx.fillStyle = col.ribbon;
        ctx.beginPath();
        ctx.arc(x, y, r0, 0, Math.PI * 2);
        ctx.fill();
        ctx.globalAlpha = 0.85;
        ctx.lineWidth = 1.6;
        ctx.strokeStyle = col.ribbon;
        ctx.stroke();
      }
      ctx.globalAlpha = 1;
    }

    // Nodes that changed while the learner was looking: a pulse that fades out. The camera does not move for them
    if (flash.current.size) {
      const t0 = performance.now();
      ctx.lineWidth = 2;
      ctx.strokeStyle = col.ribbon;
      for (const [key, start] of flash.current) {
        const age = (t0 - start) / FLASH_MS;
        if (age >= 1) {
          flash.current.delete(key);
          continue;
        }
        const p = pos(key);
        if (!p) continue;
        const phase = (age * 2) % 1;
        ctx.globalAlpha = 0.9 * (1 - age) * (1 - phase);
        ctx.beginPath();
        ctx.arc(sx(p.x), sy(p.y), (key.startsWith("h:") ? rH : rT) + 4 + 14 * phase, 0, Math.PI * 2);
        ctx.stroke();
      }
      ctx.globalAlpha = 1;
    }

    // Labels. A topic label fades with the size of a slot on screen, a hub label later: on the far view the hubs are
    // what the eye holds on to. Labels never overlap: the more important one stays (hub, then hovered, then busier topic).
    const now = performance.now();
    const dt = Math.min(100, now - lastDraw.current);
    lastDraw.current = now;
    const ease = 1 - Math.exp(-dt / 90);
    const unit = GAP_X * k;
    const fadeTopic = smooth(40, 78, unit);
    const fadeHub = smooth(8, 26, unit);
    type Label = { key: string; text: string; x: number; y: number; above: boolean; prio: number; fade: number; deg: number; fill: string; font: string };
    const labels: Label[] = [];
    const hubFont = `500 12px ${col.label}`;
    const topicFont = `400 11px ${col.body}`;
    for (const n of L.hubs) {
      const p = pos(n.key);
      if (!p) continue;
      const x = sx(p.x), y = sy(p.y);
      if (!near(x, y, 120)) continue;
      labels.push({ key: n.key, text: (hubs.get(n.id)?.name ?? "").toUpperCase(), x, y: y - rH - 5, above: true, prio: 3, fade: fadeHub, deg: 0, fill: col.paper, font: hubFont });
    }
    for (const n of L.topics) {
      const p = pos(n.key);
      const t = topics.get(n.id);
      if (!p || !t) continue;
      const x = sx(p.x), y = sy(p.y);
      if (!near(x, y, 120)) continue;
      const hot = n.key === hovered;
      labels.push({ key: n.key, text: t.name, x, y: y + rT + 4, above: false, prio: hot ? 2 : 1, fade: hot ? 1 : fadeTopic, deg: links.degree.get(n.id) ?? 0, fill: hot ? col.paper : col.dim, font: topicFont });
    }
    labels.sort((a, b) => b.prio - a.prio || b.deg - a.deg || (a.key < b.key ? -1 : 1));
    // Boxes already taken, in a coarse grid so a crowded graph stays cheap
    const CELL = 80;
    const grid = new Map<string, { x0: number; y0: number; x1: number; y1: number }[]>();
    const cellsOf = (bx: { x0: number; y0: number; x1: number; y1: number }) => {
      const out: string[] = [];
      for (let gx = Math.floor(bx.x0 / CELL); gx <= Math.floor(bx.x1 / CELL); gx++) for (let gy = Math.floor(bx.y0 / CELL); gy <= Math.floor(bx.y1 / CELL); gy++) out.push(`${gx},${gy}`);
      return out;
    };
    let settling = false;
    ctx.textAlign = "center";
    ctx.lineJoin = "round";
    ctx.textBaseline = "alphabetic";
    for (const lb of labels) {
      let target = 0;
      if (lb.fade > 0.02) {
        const wKey = `${lb.font}|${lb.text}`;
        let tw = textW.current.get(wKey);
        if (tw === undefined) {
          ctx.font = lb.font;
          tw = ctx.measureText(lb.text).width;
          textW.current.set(wKey, tw);
        }
        const hgt = 13;
        const bx = { x0: lb.x - tw / 2 - 3, x1: lb.x + tw / 2 + 3, y0: lb.above ? lb.y - hgt : lb.y - 1, y1: lb.above ? lb.y + 2 : lb.y + hgt };
        const cells = cellsOf(bx);
        const clash = cells.some((c) => (grid.get(c) ?? []).some((o) => bx.x0 < o.x1 && bx.x1 > o.x0 && bx.y0 < o.y1 && bx.y1 > o.y0));
        if (!clash) {
          target = 1;
          for (const c of cells) grid.set(c, [...(grid.get(c) ?? []), bx]);
        }
      }
      const was = labelVis.current.get(lb.key) ?? 0;
      const vis = Math.abs(target - was) < 0.01 ? target : was + (target - was) * ease;
      if (vis !== target) settling = true;
      labelVis.current.set(lb.key, vis);
      const alpha = lb.fade * vis;
      if (alpha < 0.02) continue;
      ctx.font = lb.font;
      ctx.globalAlpha = alpha;
      ctx.lineWidth = lb.above ? 4 : 3;
      ctx.strokeStyle = col.cloth;
      ctx.textBaseline = lb.above ? "bottom" : "top";
      ctx.strokeText(lb.text, lb.x, lb.y);
      ctx.fillStyle = lb.fill;
      ctx.fillText(lb.text, lb.x, lb.y);
    }
    ctx.globalAlpha = 1;
    return settling || flash.current.size > 0;
  }, []);

  const frame = useCallback(
    (now: number) => {
      raf.current = 0;
      let again = false;
      if (posTween.current !== null) {
        const t = clamp((now - posTween.current) / posMs.current, 0, 1);
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
      if (draw()) again = true;
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

  // Where the camera stands, kept per domain on this device: the world point at the centre of the graph area, the zoom,
  // and the topic nearest to the centre (with a few neighbours) in case that topic is gone next time
  const saveNow = useCallback(() => {
    clearTimeout(camTimer.current);
    const { w, h } = sizeRef.current;
    if (!w || !h) return;
    const cw = scene.current.colW;
    const v = view.current;
    const cx = (cw + (w - cw) / 2 - v.tx) / v.k;
    const cy = (h / 2 - v.ty) / v.k;
    const near = [...target.current]
      .filter(([key]) => !key.startsWith("h:"))
      .map(([id, p]) => ({ id, x: p.x, y: p.y, d: Math.hypot(p.x - cx, p.y - cy) }))
      .sort((a, b) => a.d - b.d)
      .slice(0, 4)
      .map(({ id, x, y }) => ({ id, x, y }));
    const cam: SavedCamera = { k: v.k, cx, cy, anchor: near[0], near: near.slice(1) };
    saveCamera(LEARNER, scene.current.model.domainId, cam);
  }, []);
  const queueSave = useCallback(() => {
    clearTimeout(camTimer.current);
    camTimer.current = setTimeout(saveNow, 500);
  }, [saveNow]);

  const moveView = useCallback(
    (to: View, animate: boolean) => {
      if (animate && !reducedMotion()) viewTween.current = { start: performance.now(), from: view.current, to };
      else {
        viewTween.current = null;
        view.current = to;
      }
      schedule();
      queueSave();
    },
    [schedule, queueSave],
  );

  const fitView = useCallback((w: number, h: number): View => {
    const { x0, x1, y0, y1 } = scene.current.layout.bounds;
    // The graph lives to the right of the column
    const cw = scene.current.colW;
    const k = clamp(Math.min((w - cw - FIT_MARGIN * 2) / Math.max(1, x1 - x0), (h - FIT_MARGIN * 2) / Math.max(1, y1 - y0)), K_MIN, FIT_K_MAX);
    return { k, tx: cw + (w - cw) / 2 - ((x0 + x1) / 2) * k, ty: h / 2 - ((y0 + y1) / 2) * k };
  }, []);

  // First view of a domain: where the learner stood last time, else the whole graph
  const initialView = useCallback(
    (w: number, h: number): View => {
      const saved = loadCamera(LEARNER, scene.current.model.domainId);
      if (!saved) return fitView(w, h);
      const k = clamp(saved.k, K_MIN, K_MAX);
      const c = restoreCenter(saved, (id) => target.current.get(id));
      const cw = scene.current.colW;
      return { k, tx: cw + (w - cw) / 2 - c.x * k, ty: h / 2 - c.y * k };
    },
    [fitView],
  );

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
      if (!fitted.current) {
        fitted.current = true;
        view.current = initialView(size.w, size.h);
      }
      // Resizing clears the canvas: paint at once so there is no blank frame
      draw();
    }
    schedule();
  }, [size, initialView, schedule, draw]);

  // A new layout: known nodes stay, whatever moved glides to its place
  useEffect(() => {
    const was = scene.current.layout.unlinked;
    scene.current = { layout, model, topicMap, hubMap, colW: column.width, links };
    savePositions(LEARNER, model.domainId, layout);
    const first = shown.current.size === 0;
    from.current = new Map(shown.current);
    target.current = new Map([...layout.nodes.values()].map((n) => [n.key, { x: n.x, y: n.y }]));
    // A new node appears where it belongs, it does not fly in from the corner.
    // A topic that just got a link starts from its spot in the column, so the learner sees where it went
    let fromColumn = false;
    const { k, tx: vx, ty: vy } = view.current;
    for (const [key, to] of target.current) {
      if (from.current.has(key)) continue;
      const cy = was.includes(key) ? colY.current.get(key) : undefined;
      if (!first && cy !== undefined) {
        from.current.set(key, { x: (COL_W + 6 - vx) / k, y: (cy - vy) / k });
        fromColumn = true;
      } else from.current.set(key, to);
    }
    posMs.current = fromColumn ? MOVE_MS : TWEEN_MS;
    if (first || reducedMotion()) {
      shown.current = new Map(target.current);
      posTween.current = null;
    } else posTween.current = performance.now();
    schedule();
  }, [layout, model, topicMap, hubMap, column.width, links, schedule]);

  // Where each column item stands (for the lines to hubs). Measured after the column is laid out and whenever it scrolls
  const measureColumn = useCallback(() => {
    const box = colScroll.current;
    const next = new Map<string, number>();
    if (box) for (const [id, el] of colEls.current) next.set(id, el.offsetTop - box.scrollTop + el.offsetHeight / 2);
    colY.current = next;
    schedule();
  }, [schedule]);
  useEffect(() => {
    const id = requestAnimationFrame(measureColumn);
    return () => cancelAnimationFrame(id);
  }, [column, size.h, measureColumn]);

  // Strict Mode runs this cleanup once in development: forget the cancelled frame so the loop can restart
  useEffect(
    () => () => {
      cancelAnimationFrame(raf.current);
      raf.current = 0;
    },
    [],
  );

  // What the learner has seen: the camera is saved when it settles and when they leave
  useEffect(() => {
    const domainId = model.domainId;
    enterDomain(domainId, scene.current.model);
    const onHide = () => {
      saveNow();
      saveAllVisits();
    };
    window.addEventListener("pagehide", onHide);
    return () => {
      window.removeEventListener("pagehide", onHide);
      saveNow();
      leaveDomain(domainId);
    };
  }, [model.domainId, saveNow]);

  // A "Today" card under the pointer lights its node
  useEffect(() => {
    lit.current = [...(highlight?.topicIds ?? []), ...(highlight?.hubIds ?? []).map((id) => `h:${id}`)];
    schedule();
  }, [highlight, schedule]);

  // The graph changed while it is on screen: what changed pulses, and counts as new. The camera stays where it is
  useEffect(() => {
    const fresh = updateDomain(model.domainId, model);
    const t0 = performance.now();
    for (const id of fresh.topics) flash.current.set(id, t0);
    for (const id of fresh.hubs) flash.current.set(`h:${id}`, t0);
    if (fresh.topics.size || fresh.hubs.size) schedule();
  }, [model, schedule]);

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
    if (d?.moved) queueSave();
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
      const cw = scene.current.colW;
      const mid = cw + (w - cw) / 2;
      moveView({ k, tx: mid - p.x * k, ty: h / 2 - p.y * k }, true);
      hoverKey.current = id;
      setHover({ id, x: mid, y: h / 2 });
    },
    [moveView],
  );
  useImperativeHandle(ref, () => ({ focusTopic }), [focusTopic]);

  const enterItem = (id: string) => {
    clearTimeout(hideTimer.current);
    hoverKey.current = id;
    setHover({ id, x: COL_W, y: colY.current.get(id) ?? 0 });
  };

  /** One group of the column. Names wrap instead of being cut, so a label is always whole */
  const group = (title: string, items: { topic: GraphTopic; domainName?: string }[], first: boolean) =>
    items.length === 0 ? null : (
      <section className={first ? "" : "mt-4 border-t border-seam-soft pt-3"}>
        <h3 className="caps px-4 pb-1 text-paper-dim">{title}</h3>
        <ul>
          {items.map(({ topic, domainName }) => (
            <li
              key={topic.id}
              ref={(el) => {
                if (el) colEls.current.set(topic.id, el);
                else colEls.current.delete(topic.id);
              }}
              onPointerEnter={() => enterItem(topic.id)}
              onPointerLeave={() => setHoverKey(null)}
            >
              <Link
                href={`/topic/${topic.id}`}
                className="flex items-start gap-2.5 px-4 py-2 text-small text-paper outline-none transition-colors duration-(--dur-s) ease-(--ease-out) hover:bg-cloth-hover focus-visible:bg-cloth-hover"
                style={{ opacity: topic.status === "proposed" ? 0.65 : 1 }}
              >
                <StateDot state={stateOf(topic, model.nowMs)} className="mt-1.5" />
                <span className="min-w-0">
                  {topic.name}
                  {domainName && <span className="caps mt-0.5 block text-paper-dim">{domainName}</span>}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      </section>
    );

  const hoverTopic = hover ? lookup.get(hover.id) : undefined;
  const hoverMock = hover ? domain.topics.find((t) => t.id === hover.id) : undefined;
  const hubCount = model.hubs.filter((h) => h.kind !== "domain_all").length;
  const topicCount = model.topics.filter(onGraph).length;
  const allHub = model.hubs.find((h) => h.kind === "domain_all");
  // Centre of the part of the box the graph can use
  const cx = column.width + (size.w - column.width) / 2;

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
            <IconButton label={tx.graph.zoomIn} onClick={() => zoomAt(cx, size.h / 2, 1.25)}>
              <Plus />
            </IconButton>
            <IconButton label={tx.graph.zoomOut} onClick={() => zoomAt(cx, size.h / 2, 0.8)}>
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
            "+": () => zoomAt(cx, size.h / 2, 1.25),
            "=": () => zoomAt(cx, size.h / 2, 1.25),
            "-": () => zoomAt(cx, size.h / 2, 0.8),
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

        {column.width > 0 && (
          <nav
            ref={colScroll}
            aria-label={tx.graph.columnLabel}
            onScroll={measureColumn}
            className="absolute inset-y-0 left-0 z-[5] overflow-y-auto border-r border-seam-soft bg-cloth py-3"
            style={{ width: column.width }}
          >
            {group(tx.graph.columnFree, column.free.map((t) => ({ topic: t })), true)}
            {group(tx.graph.columnOther, column.outside, column.free.length === 0)}
          </nav>
        )}

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
