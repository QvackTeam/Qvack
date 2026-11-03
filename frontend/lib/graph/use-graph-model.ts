"use client";

import { useEffect, useSyncExternalStore } from "react";
import { API_MODE } from "@/lib/api/client";
import type { Locale } from "@/lib/i18n/locale";
import { getGraphModel, installGraphDevHandle, subscribeGraph } from "./mock";
import type { GraphModel } from "./types";

/** The graph of a domain, live: on mocks it follows edits; with the API on it is `undefined` until the adapter exists */
export function useGraphModel(locale: Locale, domainId: string): GraphModel | undefined {
  useEffect(installGraphDevHandle, []);
  const get = () => (API_MODE ? undefined : getGraphModel(locale, domainId));
  return useSyncExternalStore(subscribeGraph, get, get);
}
