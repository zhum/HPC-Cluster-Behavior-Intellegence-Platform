export interface TensorRequest {
  start: string;
  end: string;
  resolution_s: number;
  nodes?: string[] | null;
  metrics?: string[] | null;
}

export interface SessionStatus {
  session_id: string;
  status: "pending" | "ready" | "error";
  error?: string | null;
  n_nodes?: number | null;
  n_metrics?: number | null;
  n_timesteps?: number | null;
  nodes?: string[] | null;
  metrics?: string[] | null;
  inactive_nodes?: string[] | null;
  times?: string[] | null;
}

export interface EmbeddingResponse {
  E: [number, number][];
  inactive_flags: boolean[];
  cache_key: string;
  timings_ms: Record<string, number>;
}

export interface ClustersResponse {
  labels: number[];
  centroids: number[][];
  quality_metrics: Record<string, number>;
  cache_key: string;
  timings_ms: Record<string, number>;
}

export interface ExplainResult {
  cluster: number;
  weights: number[];
  ranked_metrics: string[];
  alpha: number;
}

export interface ExplainResponse {
  results: ExplainResult[];
  cache_key: string;
  timings_ms: Record<string, number>;
}

export interface NullSegment {
  node_id: string;
  seg_start: string;
  seg_end: string;
}

export interface TimeDomainResponse {
  clusters: Record<string, NullSegment[]>;
  cache_key: string;
  timings_ms: Record<string, number>;
}

export interface ClusterMeansResponse {
  times: string[];
  polylines: Record<string, Record<string, number[]>>;
  cache_key: string;
  timings_ms: Record<string, number>;
}

export type Band = "5m" | "30m" | "2h" | "24h" | "7d";

export interface ZScoresResponse {
  z: number[][];
  metrics: string[];
  node_ids: string[];
  baseline_windows: Record<string, [number, number]>;
  band: string;
  segment_used: Record<string, [number, number]>;
  degenerate_metrics: string[];
  cache_key: string;
  timings_ms: Record<string, number>;
}

export interface BaselineResponse {
  window: [number, number];
  iqr: [number, number];
  cache_key: string;
  timings_ms: Record<string, number>;
}

export interface RawSeriesResponse {
  times: string[];
  series: Record<string, Record<string, number[]>>;
  cache_key: string;
  timings_ms: Record<string, number>;
}

export interface JobInterval {
  job_id: string;
  user: string;
  partition: string;
  node_id: string;
  state: string;
  start: string;
  end: string | null;
}

export interface JobsOverlayResponse {
  intervals: JobInterval[];
  unmapped_nodes: string[];
  cache_key: string;
  timings_ms: Record<string, number>;
}
