import { onGraph, type GraphModel } from "./types";

/** Step between neighbours, world units */
export const GAP_X = 130;
export const GAP_Y = 140;
/** Next to a topic of another hub the step is this many times wider: hubs read as separate branches */
const FOREIGN_GAP = 2.3;
/** How strongly a topic is pulled to the lane of its own hub (0 = only by its links, 1 = only by the hub) */
const HUB_PULL = 0.88;
/** A hub stands this far above the highest of its topics */
const HUB_RISE = GAP_Y * 0.9;
/** Hubs are bigger than topics and need more room */
const HUB_GAP_X = GAP_X * 1.35;

export type LayoutNode = {
  /** Topic id, or `h:<id>` for a hub */
  key: string;
  id: string;
  kind: "topic" | "hub";
  x: number;
  /** Up is negative: the foundation is at y = 0 */
  y: number;
  layer: number;
};

export type Layout = {
  nodes: Map<string, LayoutNode>;
  topics: LayoutNode[];
  hubs: LayoutNode[];
  /** Topics with no "needed before" link at all. They do not belong in the chains (they go to the left column) */
  unlinked: string[];
  bounds: { x0: number; y0: number; x1: number; y1: number };
};

/** Saved `[x, layer]` per node key. Known nodes keep their x: that is what keeps the graph steady */
export type StoredPositions = Record<string, [number, number]>;

export const hubKey = (id: string) => `h:${id}`;

/** Tarjan. Edges go from a topic to its prerequisites, so prerequisites come out first */
function scc(n: number, out: number[][]): number[][] {
  const index = new Array<number>(n).fill(-1);
  const low = new Array<number>(n).fill(0);
  const on = new Array<boolean>(n).fill(false);
  const stack: number[] = [];
  const comps: number[][] = [];
  let counter = 0;
  const visit = (v: number) => {
    index[v] = low[v] = counter++;
    stack.push(v);
    on[v] = true;
    for (const w of out[v]) {
      if (index[w] < 0) {
        visit(w);
        low[v] = Math.min(low[v], low[w]);
      } else if (on[w]) low[v] = Math.min(low[v], index[w]);
    }
    if (low[v] === index[v]) {
      const comp: number[] = [];
      let w: number;
      do {
        w = stack.pop()!;
        on[w] = false;
        comp.push(w);
      } while (w !== v);
      comps.push(comp);
    }
  };
  for (let v = 0; v < n; v++) if (index[v] < 0) visit(v);
  return comps;
}

/** Nearest x to `want` at least `gap` away from everything in `taken`. Deterministic: right side first */
function freeSlot(want: number, taken: number[], gap: number): number {
  const free = (x: number) => taken.every((t) => Math.abs(t - x) >= gap - 1e-6);
  if (free(want)) return want;
  const step = gap / 2;
  for (let k = 1; k <= taken.length * 2 + 2; k++) {
    if (free(want + k * step)) return want + k * step;
    if (free(want - k * step)) return want - k * step;
  }
  return want;
}

const mean = (xs: number[]) => xs.reduce((a, b) => a + b, 0) / xs.length;

/**
 * Bottom-up layered layout. No physics, same data gives the same picture.
 * A topic stands above everything it needs; cycles are collapsed into one layer, side by side.
 * With saved positions a known topic keeps its x, a new one takes the nearest free place in its layer.
 */
/** Topics that have at least one "needed before" link, and those links. The rest go to the left column */
export function chainOf(model: GraphModel) {
  const visible = model.topics.filter(onGraph);
  const ids = new Set(visible.map((t) => t.id));
  const edges = model.requires.filter((e) => ids.has(e.topicId) && ids.has(e.requiresId) && e.topicId !== e.requiresId);
  const linked = new Set(edges.flatMap((e) => [e.topicId, e.requiresId]));
  return { topics: visible.filter((t) => linked.has(t.id)), edges, unlinked: visible.filter((t) => !linked.has(t.id)).map((t) => t.id) };
}

export function layoutGraph(model: GraphModel, stored?: StoredPositions): Layout {
  const { topics, edges, unlinked } = chainOf(model);

  const n = topics.length;
  const at = new Map(topics.map((t, i) => [t.id, i]));
  const req: number[][] = topics.map(() => []);
  const dep: number[][] = topics.map(() => []);
  for (const e of edges) {
    const a = at.get(e.topicId)!;
    const b = at.get(e.requiresId)!;
    req[a].push(b);
    dep[b].push(a);
  }

  // Layer = longest chain below, taken on the condensation (prerequisite components come out first)
  const comps = scc(n, req);
  const compOf = new Array<number>(n).fill(0);
  comps.forEach((c, ci) => c.forEach((v) => (compOf[v] = ci)));
  const compLayer = new Array<number>(comps.length).fill(0);
  comps.forEach((c, ci) => {
    let l = 0;
    for (const v of c) for (const w of req[v]) if (compOf[w] !== ci) l = Math.max(l, compLayer[compOf[w]] + 1);
    compLayer[ci] = l;
  });
  const layerOf = topics.map((_, i) => compLayer[compOf[i]]);
  const depth = n ? Math.max(...layerOf) + 1 : 0;
  const rows: number[][] = Array.from({ length: depth }, () => []);
  layerOf.forEach((l, i) => rows[l].push(i));

  // The hub a topic stands in (the first chapter that lists it); -1 for a free topic. `domain_all` is not a chapter
  const hubIdx = new Map(model.hubs.filter((h) => h.kind !== "domain_all").map((h, i) => [h.id, i]));
  const ownHub = new Array<number>(n).fill(-1);
  for (const l of model.includes) {
    const i = at.get(l.topicId);
    const h = hubIdx.get(l.hubId);
    if (i !== undefined && h !== undefined && ownHub[i] < 0) ownHub[i] = h;
  }

  const x = new Array<number>(n).fill(NaN);
  const byComp = (a: number, b: number) => compOf[a] - compOf[b] || (topics[a].id < topics[b].id ? -1 : topics[a].id > topics[b].id ? 1 : 0);
  /** Left to right, no closer than the step (wider between two hubs); the row keeps its middle */
  const gapBetween = (a: number, b: number) => (ownHub[a] !== ownHub[b] ? GAP_X * FOREIGN_GAP : GAP_X);
  const spread = (row: number[], want?: Map<number, number>) => {
    const t = row.map((v, r) => want?.get(v) ?? (r - (row.length - 1) / 2) * GAP_X);
    const p = [...t];
    for (let r = 1; r < row.length; r++) p[r] = Math.max(p[r], p[r - 1] + gapBetween(row[r - 1], row[r]));
    const shift = mean(t) - mean(p);
    row.forEach((v, r) => (x[v] = p[r] + shift));
  };

  if (!stored || !topics.some((t) => stored[t.id])) {
    // First layout: order each layer by the mean x of its neighbours, a few sweeps
    // Start: every hub gets its own lane, left to right in the order of the hubs; free topics go by their links
    const laneWidth = new Map<number, number>();
    for (const row of rows) {
      const cnt = new Map<number, number>();
      for (const v of row) if (ownHub[v] >= 0) cnt.set(ownHub[v], (cnt.get(ownHub[v]) ?? 0) + 1);
      for (const [h, c] of cnt) laneWidth.set(h, Math.max(laneWidth.get(h) ?? 0, c));
    }
    const lane = new Map<number, number>();
    let cursor = 0;
    for (const h of [...laneWidth.keys()].sort((a, b) => a - b)) {
      const w = (laneWidth.get(h)! - 1) * GAP_X;
      lane.set(h, cursor + w / 2);
      cursor += w + GAP_X * FOREIGN_GAP;
    }
    const mid = cursor ? (cursor - GAP_X * FOREIGN_GAP) / 2 : 0;
    for (const row of rows) {
      row.sort((a, b) => (ownHub[a] < 0 ? Infinity : lane.get(ownHub[a])!) - (ownHub[b] < 0 ? Infinity : lane.get(ownHub[b])!) || byComp(a, b));
      // the topics of one hub in this layer stand side by side around the hub's lane
      const total = new Map<number, number>();
      for (const v of row) total.set(ownHub[v], (total.get(ownHub[v]) ?? 0) + 1);
      const seen = new Map<number, number>();
      const start = new Map<number, number>();
      row.forEach((v, r) => {
        const h = ownHub[v];
        const k = seen.get(h) ?? 0;
        seen.set(h, k + 1);
        start.set(v, h >= 0 ? lane.get(h)! - mid + (k - (total.get(h)! - 1) / 2) * GAP_X : (r - (row.length - 1) / 2) * GAP_X);
      });
      spread(row, start);
    }
    const sweep = (layers: number[], nb: number[][]) => {
      for (const l of layers) {
        const row = rows[l];
        // pulled by the neighbours it is linked to and by the middle of its own hub
        const aim = new Map(
          row.map((v) => {
            const link = nb[v].length ? mean(nb[v].map((w) => x[w])) : x[v];
            const home = ownHub[v] >= 0 ? lane.get(ownHub[v])! - mid : NaN;
            return [v, Number.isNaN(home) ? link : link * (1 - HUB_PULL) + home * HUB_PULL] as [number, number];
          }),
        );
        row.sort((a, b) => aim.get(a)! - aim.get(b)! || byComp(a, b));
        spread(row, aim);
      }
    };
    const up = Array.from({ length: depth }, (_, i) => i);
    for (let it = 0; it < 6; it++) {
      sweep(up.slice(1), req);
      sweep([...up].reverse().slice(1), dep);
    }
  } else {
    // Later layouts: topics that stayed in their layer keep x; the rest are inserted at the nearest free place
    const fixed = new Set<number>();
    topics.forEach((t, i) => {
      const s = stored[t.id];
      if (s && s[1] === layerOf[i]) {
        x[i] = s[0];
        fixed.add(i);
      }
    });
    const loose = topics.map((_, i) => i).filter((i) => !fixed.has(i)).sort((a, b) => layerOf[a] - layerOf[b] || byComp(a, b));
    for (const v of loose) {
      const near = [...req[v], ...dep[v]].map((w) => x[w]).filter((p) => !Number.isNaN(p));
      const row = rows[layerOf[v]].filter((w) => w !== v && !Number.isNaN(x[w])).map((w) => x[w]);
      const was = stored[topics[v].id]?.[0];
      const want = near.length ? mean(near) : was !== undefined ? was : row.length ? mean(row) : 0;
      x[v] = freeSlot(want, row, GAP_X);
    }
  }

  const nodes = new Map<string, LayoutNode>();
  const topicNodes = topics.map((t, i): LayoutNode => {
    const node = { key: t.id, id: t.id, kind: "topic" as const, x: x[i], y: -layerOf[i] * GAP_Y, layer: layerOf[i] };
    nodes.set(node.key, node);
    return node;
  });

  // Hubs: above the highest of their topics, near the middle of them unless they already have a saved place
  const topY = topicNodes.length ? Math.min(...topicNodes.map((t) => t.y)) : 0;
  const members = new Map<string, LayoutNode[]>();
  for (const l of model.includes) {
    const t = nodes.get(l.topicId);
    if (t) members.set(l.hubId, [...(members.get(l.hubId) ?? []), t]);
  }
  const hubNodes: LayoutNode[] = [];
  const placed: LayoutNode[] = [...topicNodes];
  const hubs = model.hubs
    .filter((h) => h.kind !== "domain_all")
    .map((h) => {
      const m = members.get(h.id) ?? [];
      return { h, m, y: (m.length ? Math.min(...m.map((t) => t.y)) : topY) - HUB_RISE };
    })
    .sort((a, b) => a.y - b.y || (a.h.id < b.h.id ? -1 : 1));
  for (const { h, m, y } of hubs) {
    const s = stored?.[hubKey(h.id)];
    const want = s ? s[0] : m.length ? mean(m.map((t) => t.x)) : 0;
    const row = placed.filter((p) => Math.abs(p.y - y) < GAP_Y * 0.55).map((p) => p.x);
    const node: LayoutNode = { key: hubKey(h.id), id: h.id, kind: "hub", x: freeSlot(want, row, HUB_GAP_X), y, layer: Math.round(-y / GAP_Y) };
    nodes.set(node.key, node);
    hubNodes.push(node);
    placed.push(node);
  }

  const all = [...topicNodes, ...hubNodes];
  const bounds = all.length
    ? { x0: Math.min(...all.map((p) => p.x)), x1: Math.max(...all.map((p) => p.x)), y0: Math.min(...all.map((p) => p.y)), y1: Math.max(...all.map((p) => p.y)) }
    : { x0: 0, x1: 0, y0: 0, y1: 0 };
  return { nodes, topics: topicNodes, hubs: hubNodes, unlinked, bounds };
}

const KEY = (learner: string, domainId: string) => `quack.graph.${learner}.${domainId}.pos`;

export function loadPositions(learner: string, domainId: string): StoredPositions | undefined {
  try {
    const raw = localStorage.getItem(KEY(learner, domainId));
    if (!raw) return undefined;
    const v = JSON.parse(raw) as { v?: number; pos?: StoredPositions };
    return v.v === 3 && v.pos && typeof v.pos === "object" ? v.pos : undefined;
  } catch {
    return undefined;
  }
}

export function savePositions(learner: string, domainId: string, layout: Layout) {
  const pos: StoredPositions = {};
  for (const n of layout.nodes.values()) pos[n.key] = [Math.round(n.x * 10) / 10, n.layer];
  try {
    localStorage.setItem(KEY(learner, domainId), JSON.stringify({ v: 3, pos }));
  } catch {
    /* no storage: the layout is recomputed next time */
  }
}
