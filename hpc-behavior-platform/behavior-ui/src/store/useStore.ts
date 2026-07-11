import { create } from "zustand";
import type { Band } from "../api/types";

export interface UmapParams {
  n_neighbors: number;
  min_dist: number;
  random_state: number;
}

export interface HoveredCell {
  metric: string;
  nodeId: string;
}

export interface CrossViewState {
  session: string | null;
  timeWindow: [number, number] | null; // [t0, t1] index range, null = full range
  umapParams: UmapParams;
  k: number;
  selectedClusterIds: number[];
  lassoNodeIds: string[];
  selectedMetrics: string[];
  band: Band;
  baselines: Record<string, [number, number]>;
  hoveredCell: HoveredCell | null;

  setSession: (session: string | null) => void;
  setTimeWindow: (window: [number, number] | null) => void;
  setUmapParams: (params: UmapParams) => void;
  resetUmapDefaults: () => void;
  setK: (k: number) => void;
  setSelectedClusterIds: (ids: number[]) => void;
  setLassoNodeIds: (ids: string[]) => void;
  setSelectedMetrics: (metrics: string[]) => void;
  setBand: (band: Band) => void;
  setBaseline: (metric: string, window: [number, number]) => void;
  clearBaseline: (metric: string) => void;
  setHoveredCell: (cell: HoveredCell | null) => void;
}

export const DEFAULT_UMAP_PARAMS: UmapParams = { n_neighbors: 15, min_dist: 0.1, random_state: 42 };

export const useStore = create<CrossViewState>((set) => ({
  session: null,
  timeWindow: null,
  umapParams: DEFAULT_UMAP_PARAMS,
  k: 4,
  selectedClusterIds: [],
  lassoNodeIds: [],
  selectedMetrics: [],
  band: "2h",
  baselines: {},
  hoveredCell: null,

  setSession: (session) => set({ session }),
  setTimeWindow: (timeWindow) => set({ timeWindow }),
  setUmapParams: (umapParams) => set({ umapParams }),
  resetUmapDefaults: () => set({ umapParams: DEFAULT_UMAP_PARAMS, k: 4 }),
  setK: (k) => set({ k }),
  setSelectedClusterIds: (selectedClusterIds) => set({ selectedClusterIds }),
  setLassoNodeIds: (lassoNodeIds) => set({ lassoNodeIds }),
  setSelectedMetrics: (selectedMetrics) => set({ selectedMetrics }),
  setBand: (band) => set({ band }),
  setBaseline: (metric, window) =>
    set((state) => ({ baselines: { ...state.baselines, [metric]: window } })),
  clearBaseline: (metric) =>
    set((state) => {
      const next = { ...state.baselines };
      delete next[metric];
      return { baselines: next };
    }),
  setHoveredCell: (hoveredCell) => set({ hoveredCell }),
}));
