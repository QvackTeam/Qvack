import type { Locale } from "@/lib/i18n/locale";
import { getMocks, MOCK_TODAY } from "@/lib/mock";
import type { DisplayCode, GraphHub, GraphModel, GraphTopic, HubLink } from "./types";

const DAY = 86_400_000;
const clean = (s: string) => s.replace(/­/g, "");
export const MOCK_NOW_MS = Date.parse(MOCK_TODAY) + 12 * 3_600_000;

/** Stable 0..1 from an id, so mocks do not change between renders */
const hash01 = (id: string) => {
  let h = 0;
  for (const c of id) h = (h * 31 + c.charCodeAt(0)) % 9973;
  return h / 9973;
};

type Kind = "solid" | "review" | "proposed" | "hidden" | DisplayCode;

function topicOf(id: string, name: string, kind: Kind): GraphTopic {
  const r = hash01(id);
  if (kind === "proposed") return { id, name, status: "proposed", visibility: "pale" };
  if (kind === "hidden") return { id, name, status: "hidden", visibility: "hidden" };
  const code: DisplayCode = kind === "solid" || kind === "review" ? "solved_independently" : kind;
  // solid: review is ahead; everything else is overdue
  const due = kind === "solid" ? MOCK_NOW_MS + Math.round(3 + r * 15) * DAY : MOCK_NOW_MS - Math.round(1 + r * 8) * DAY;
  return { id, name, status: "active", visibility: "shown", displayState: code, nearestDueAtMs: due };
}

/** Calculus, built from the existing presentation mock */
function matanGraph(locale: Locale): GraphModel | undefined {
  const domain = getMocks(locale).domains.find((d) => d.id === "matan");
  if (!domain) return undefined;
  const topics = domain.topics.map((t) => topicOf(t.id, clean(t.title), t.state === "solid" ? "solid" : t.state === "review" ? "review" : t.state === "confused" ? "persistent_error" : "proposed"));
  const hubs: GraphHub[] = domain.hubs.map((h) => ({
    id: h.id,
    name: clean(h.title),
    kind: h.deadline ? "deadline" : "material",
    deadlineAtMs: h.deadline ? Date.parse(h.deadline.date) : undefined,
  }));
  hubs.push({ id: "all", name: domain.title, kind: "domain_all" });
  return {
    domainId: domain.id,
    domainName: domain.title,
    topics,
    hubs,
    includes: domain.topics.filter((t) => t.hubId).map((t) => ({ hubId: t.hubId!, topicId: t.id })),
    requires: domain.topics.flatMap((t) => t.requires.map((r) => ({ topicId: t.id, requiresId: r }))),
    nowMs: MOCK_NOW_MS,
  };
}

type Row = { id: string; en: string; ru: string; requires: string[]; hubs: string[]; kind: Kind };

/**
 * Linear algebra: the awkward cases of the slice. A cycle in "needed before" (span, independence),
 * topics in two hubs, a hidden topic, a hub with a deadline, a topic with no links at all.
 */
const ROWS: Row[] = [
  { id: "vec", en: "Vectors", ru: "Векторы", requires: [], hubs: ["vectors"], kind: "solid" },
  { id: "dot", en: "Dot product", ru: "Скалярное произведение", requires: ["vec"], hubs: ["vectors"], kind: "solid" },
  { id: "mat", en: "Matrices", ru: "Матрицы", requires: ["vec"], hubs: ["vectors"], kind: "solid" },
  { id: "matmul", en: "Matrix multiplication", ru: "Умножение матриц", requires: ["mat"], hubs: ["vectors"], kind: "review" },
  { id: "orth", en: "Orthogonality", ru: "Ортогональность", requires: ["dot"], hubs: ["vectors"], kind: "solid" },
  { id: "gauss", en: "Gaussian elimination", ru: "Метод Гаусса", requires: ["mat"], hubs: ["systems"], kind: "solid" },
  { id: "det", en: "Determinant", ru: "Определитель", requires: ["matmul"], hubs: ["systems", "colloq"], kind: "persistent_error" },
  { id: "inverse", en: "Inverse matrix", ru: "Обратная матрица", requires: ["det", "gauss"], hubs: ["systems", "colloq"], kind: "review" },
  { id: "rank", en: "Rank", ru: "Ранг", requires: ["gauss"], hubs: ["systems"], kind: "proposed" },
  { id: "span", en: "Span and basis", ru: "Линейная оболочка и базис", requires: ["vec", "indep"], hubs: ["spaces"], kind: "solid" },
  { id: "indep", en: "Linear independence", ru: "Линейная независимость", requires: ["span"], hubs: ["spaces"], kind: "inconsistent" },
  { id: "subspace", en: "Subspaces", ru: "Подпространства", requires: ["vec"], hubs: ["spaces"], kind: "solid" },
  { id: "dim", en: "Dimension", ru: "Размерность", requires: ["span", "indep"], hubs: ["spaces"], kind: "in_progress" },
  { id: "lintrans", en: "Linear maps", ru: "Линейные отображения", requires: ["mat", "subspace"], hubs: ["spaces", "colloq"], kind: "review" },
  { id: "eigval", en: "Eigenvalues", ru: "Собственные значения", requires: ["det", "lintrans"], hubs: ["colloq"], kind: "struggling" },
  { id: "eigvec", en: "Eigenvectors", ru: "Собственные векторы", requires: ["eigval"], hubs: ["colloq"], kind: "proposed" },
  { id: "diag", en: "Diagonalization", ru: "Диагонализация", requires: ["eigvec", "inverse"], hubs: ["colloq"], kind: "proposed" },
  { id: "jordan", en: "Jordan form", ru: "Жорданова форма", requires: ["diag"], hubs: ["colloq"], kind: "hidden" },
  { id: "cross", en: "Cross product", ru: "Векторное произведение", requires: [], hubs: [], kind: "solid" },
];

const LINAL = {
  en: { name: "Linear algebra", vectors: "Vectors and matrices", systems: "Linear systems", spaces: "Vector spaces", colloq: "Colloquium" },
  ru: { name: "Линейная алгебра", vectors: "Векторы и матрицы", systems: "Линейные системы", spaces: "Векторные пространства", colloq: "Коллоквиум" },
} as const;

function linalGraph(locale: Locale): GraphModel {
  const l = LINAL[locale];
  const hubIds = ["vectors", "systems", "spaces", "colloq"] as const;
  const hubs: GraphHub[] = [
    { id: "vectors", name: l.vectors, kind: "material" },
    { id: "systems", name: l.systems, kind: "request" },
    { id: "spaces", name: l.spaces, kind: "material" },
    { id: "colloq", name: l.colloq, kind: "deadline", deadlineAtMs: MOCK_NOW_MS + 12 * DAY },
    { id: "all", name: l.name, kind: "domain_all" },
  ];
  const includes: HubLink[] = hubIds.flatMap((h) => ROWS.filter((r) => r.hubs.includes(h)).map((r) => ({ hubId: h, topicId: r.id })));
  return {
    domainId: "linal",
    domainName: l.name,
    topics: ROWS.map((r) => topicOf(r.id, r[locale], r.kind)),
    hubs,
    includes,
    requires: ROWS.flatMap((r) => r.requires.map((q) => ({ topicId: r.id, requiresId: q }))),
    nowMs: MOCK_NOW_MS,
  };
}

const cache = new Map<string, GraphModel | null>();

/**
 * Graph of a domain in the slice's shape. Only on mocks: with the API on, an adapter produces the same type.
 * A domain with no topics gives `undefined`.
 */
export function getGraphModel(locale: Locale, domainId: string): GraphModel | undefined {
  const key = `${locale}:${domainId}`;
  if (!cache.has(key)) cache.set(key, domainId === "matan" ? (matanGraph(locale) ?? null) : domainId === "linal" ? linalGraph(locale) : null);
  return cache.get(key) ?? undefined;
}
