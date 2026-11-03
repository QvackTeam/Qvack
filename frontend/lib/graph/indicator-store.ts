"use client";

import { INDICATORS, type IndicatorId, type Selection } from "./indicators";

/**
 * The indicators live outside the graph (the pills stand by the sessions panel), so the two talk through this store:
 * the graph publishes what each indicator would light, the pills publish what the learner switched on.
 */
export type IndicatorState = {
  /** A graph is on screen; the pills show only then */
  mounted: boolean;
  domainId: string;
  selections: Record<IndicatorId, Selection>;
  active: ReadonlySet<IndicatorId>;
};

const none = (): Record<IndicatorId, Selection> => ({ new: { topics: [], hubs: [] }, relevant: { topics: [], hubs: [] }, deadline: { topics: [], hubs: [] }, weak: { topics: [], hubs: [] }, review: { topics: [], hubs: [] } });

let state: IndicatorState = { mounted: false, domainId: "", selections: none(), active: new Set() };
const listeners = new Set<() => void>();
const set = (next: IndicatorState) => {
  state = next;
  listeners.forEach((l) => l());
};

export const subscribeIndicators = (cb: () => void) => {
  listeners.add(cb);
  return () => void listeners.delete(cb);
};
export const getIndicators = () => state;
export const getIndicatorsServer = () => state;

const empty = (s: Selection) => s.topics.length === 0 && s.hubs.length === 0;

/** The graph tells what each indicator lights now. An indicator that ran out of nodes switches itself off */
export function publishIndicators(domainId: string, selections: Record<IndicatorId, Selection>) {
  const keep = state.domainId === domainId ? [...state.active].filter((id) => !empty(selections[id])) : [];
  // Same members: keep the same Set, so the graph does not take a data update for a click and move the camera
  const same = state.domainId === domainId && keep.length === state.active.size;
  set({ mounted: true, domainId, selections, active: same ? state.active : new Set(keep) });
}

export function unmountIndicators(domainId: string) {
  if (state.domainId === domainId) set({ mounted: false, domainId: "", selections: none(), active: new Set() });
}

export function toggleIndicator(id: IndicatorId) {
  if (empty(state.selections[id]) && !state.active.has(id)) return;
  const next = new Set(state.active);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  // Keep the fixed order, so rings are always stacked the same way
  set({ ...state, active: new Set(INDICATORS.filter((i) => next.has(i))) });
}

export function clearIndicators() {
  if (state.active.size) set({ ...state, active: new Set() });
}
