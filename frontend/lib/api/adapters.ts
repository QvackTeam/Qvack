import type { Domain, Session, TodayItem, Topic, TopicState } from "@/lib/mock/types";
import type { S } from "./client";

/** Backend → the shapes the UI was built on (lib/mock/types.ts). The UI itself does not change. */

/** displayState of the backend (Т-§22.2: 8 codes + `none`) → the four topic states of the design */
export function topicState(display: S["TopicDisplay"] | undefined): TopicState {
  switch (display?.display_state) {
    case "solved_independently":
      return "solid";
    case "confused_with":
    case "persistent_error":
    case "struggling":
      return "confused";
    case "inconsistent":
    case "in_progress":
      return "review";
    default:
      // not_tested, known_from_other_domain, none
      return "new";
  }
}

/** Ring of the topic: how far its levels have come (`display_level` 0..6), the backend has no mastery number */
const retentionOf = (display: S["TopicDisplay"] | undefined) => Math.min(1, Math.max(0, (display?.display_level ?? 0) / 6));

/** The graph already carries hubs on the backend (`GET /v1/domains/{id}/hubs`), but its nodes do not say which hub they belong to: all topics go into one chapter */
export const allTopicsHubId = (domainId: string) => `all-${domainId}`;

/** `from → to` in TopicRequires: `from` has to come before `to` */
export function topicsFromGraph(domainId: string, graph: S["DomainGraphResponse"]): Topic[] {
  const requires = new Map<string, string[]>();
  for (const e of graph.requires) requires.set(e.to_topic_id, [...(requires.get(e.to_topic_id) ?? []), e.from_topic_id]);
  // hidden and archived topics are the student's "not needed": they leave the graph
  const shown = graph.topics.filter((t) => t.status === "active" && t.visibility !== "hidden");
  const ids = new Set(shown.map((t) => t.topic_id));
  for (const [k, v] of requires) requires.set(k, v.filter((id) => ids.has(id)));
  return shown.map((t) => ({
    id: t.topic_id,
    hubId: allTopicsHubId(domainId),
    title: t.name,
    // the graph carries no descriptions: the card line is filled by the topic page
    line: "",
    simple: t.name,
    about: "",
    state: topicState(t.display),
    retention: retentionOf(t.display),
    requires: requires.get(t.topic_id) ?? [],
  }));
}

/** «С чего начнём?»: не больше стольких тем, у которых подошёл срок повторения */
const TODAY_MAX = 3;
const DAY_MS = 86_400_000;

export type TodayLabels = { reviewToday: string; reviewOverdue: (days: number) => string };

/** Темы, у которых срок повторения (`nearest_due_at_ms`, мс; 0 — не назначен) наступает до конца дня, самые давние первыми */
export function todayFromGraph(graph: S["DomainGraphResponse"], topics: Topic[], labels: TodayLabels, now = Date.now()): TodayItem[] {
  const endOfDay = new Date(now).setHours(24, 0, 0, 0);
  const shown = new Map(topics.map((t) => [t.id, t]));
  const due = (t: S["TopicNodeView"]) => t.nearest_due_at_ms ?? 0;
  return graph.topics
    .filter((t) => shown.has(t.topic_id) && due(t) > 0 && due(t) < endOfDay)
    .sort((a, b) => due(a) - due(b))
    .slice(0, TODAY_MAX)
    .map((t) => {
      const days = Math.floor((now - due(t)) / DAY_MS);
      return {
        id: t.topic_id,
        topicId: t.topic_id,
        title: shown.get(t.topic_id)!.title,
        reason: days >= 1 ? labels.reviewOverdue(days) : labels.reviewToday,
      };
    });
}

export type SessionLabels = { activeSession: string; modes: Record<string, string> };

/** Session history row → the sessions panel: topic, else the intent */
export function sessionFromApi(s: S["SessionView"], topics: Topic[], labels: SessionLabels): Session {
  const intent = s.intent ?? "free";
  const mode = labels.modes[intent] ?? intent;
  return {
    id: s.session_id,
    href: `/session/${s.session_id}`,
    date: s.started_at.slice(0, 10),
    title: topics.find((t) => t.id === s.topic_id)?.title ?? mode,
    topics: s.status === "active" ? [labels.activeSession] : [mode],
  };
}

export function domainFromApi(
  summary: S["DomainSummary"],
  graph: S["DomainGraphResponse"] | undefined,
  labels: { hub: string } & SessionLabels & TodayLabels,
  history: S["SessionView"][],
): Domain {
  const hubTitle = labels.hub;
  const topics = graph ? topicsFromGraph(summary.domain_id, graph) : [];
  const sessions = history.filter((s) => s.domain_id === summary.domain_id).map((s) => sessionFromApi(s, topics, labels));
  return {
    id: summary.domain_id,
    title: summary.name,
    titleDat: summary.name,
    hubs: topics.length ? [{ id: allTopicsHubId(summary.domain_id), num: "I", title: hubTitle, about: "" }] : [],
    topics,
    outside: [],
    sessions,
    today: graph ? todayFromGraph(graph, topics, labels) : [],
    lagging: graph?.lag_degraded,
  };
}

/** Placeholder while the list is loading or empty: the shell always has some domain */
export const EMPTY_DOMAIN: Domain = { id: "", title: "", titleDat: "", hubs: [], topics: [], outside: [], sessions: [], today: [] };
