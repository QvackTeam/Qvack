"use client";

import { useEffect, useMemo, useSyncExternalStore } from "react";
import { graphModelFromApi } from "@/lib/api/adapters";
import { API_MODE } from "@/lib/api/client";
import { useData } from "@/lib/api/data";
import type { Locale } from "@/lib/i18n/locale";
import { getGraphModel, installGraphDevHandle, subscribeGraph } from "./mock";
import type { GraphModel } from "./types";

/** The graph of a domain, live: on mocks it follows edits; with the API on it translates backend graph */
export function useGraphModel(locale: Locale, domainId: string): GraphModel | undefined {
  useEffect(installGraphDevHandle, []);
  const mockModel = useSyncExternalStore(
    subscribeGraph,
    () => (API_MODE ? undefined : getGraphModel(locale, domainId)),
    () => (API_MODE ? undefined : getGraphModel(locale, domainId)),
  );
  const data = useData();

  return useMemo(() => {
    if (!API_MODE) return mockModel;
    const rawGraph = data.graphs[domainId];
    if (!rawGraph) return undefined;
    const d = data.domains.find((x) => x.id === domainId);
    return graphModelFromApi(domainId, d?.title ?? "", rawGraph, data.history);
  }, [mockModel, data.graphs, data.domains, data.history, domainId]);
}
