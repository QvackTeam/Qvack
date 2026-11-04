"use client";

import { changesBetween, loadSnapshot, saveSnapshot, snapshotOf, type Snapshot } from "./visit";
import type { GraphModel } from "./types";

/** The learner id is unknown on mocks; the key only has to be stable on this device */
export const LEARNER = "local";

export type VisitState = {
  /** There was a snapshot from an earlier visit to compare with. Without it "New" has nothing to say */
  baseline: boolean;
  topics: ReadonlySet<string>;
  hubs: ReadonlySet<string>;
};

const EMPTY: VisitState = { baseline: false, topics: new Set(), hubs: new Set() };

type Entry = { state: VisitState; last: Snapshot; leaving?: ReturnType<typeof setTimeout> };
const entries = new Map<string, Entry>();
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());

export function subscribeVisit(cb: () => void) {
  listeners.add(cb);
  return () => void listeners.delete(cb);
}

export function getVisit(domainId: string): VisitState {
  return entries.get(domainId)?.state ?? EMPTY;
}

/** Called when the learner opens a domain: what changed since the snapshot taken when they last left */
export function enterDomain(domainId: string, model: GraphModel) {
  const known = entries.get(domainId);
  if (known?.leaving) {
    // Strict Mode or a quick re-open: the learner never left
    clearTimeout(known.leaving);
    known.leaving = undefined;
    return;
  }
  const last = snapshotOf(model);
  const base = loadSnapshot(LEARNER, domainId);
  const state: VisitState = base ? { baseline: true, ...changesBetween(base, last) } : { baseline: false, topics: new Set(), hubs: new Set() };
  entries.set(domainId, { state, last });
  emit();
}

/** The graph changed while the learner looks at it: those nodes are new too. Returns what just changed */
export function updateDomain(domainId: string, model: GraphModel): { topics: Set<string>; hubs: Set<string> } {
  const e = entries.get(domainId);
  const cur = snapshotOf(model);
  if (!e) return { topics: new Set(), hubs: new Set() };
  const fresh = changesBetween(e.last, cur);
  e.last = cur;
  if (fresh.topics.size || fresh.hubs.size) {
    e.state = {
      baseline: e.state.baseline,
      topics: new Set([...e.state.topics, ...fresh.topics]),
      hubs: new Set([...e.state.hubs, ...fresh.hubs]),
    };
    emit();
  }
  return fresh;
}

/** Called when the learner leaves: what they saw becomes the baseline for the next visit */
export function leaveDomain(domainId: string) {
  const e = entries.get(domainId);
  if (!e) return;
  clearTimeout(e.leaving);
  e.leaving = setTimeout(() => {
    saveSnapshot(LEARNER, domainId, e.last);
    entries.delete(domainId);
    emit();
  }, 0);
}

/** The tab is closing: save everything we are showing */
export function saveAllVisits() {
  for (const [id, e] of entries) saveSnapshot(LEARNER, id, e.last);
}
