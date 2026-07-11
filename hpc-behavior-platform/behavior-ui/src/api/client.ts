import type {
  BaselineResponse,
  Band,
  ClusterMeansResponse,
  ClustersResponse,
  EmbeddingResponse,
  ExplainResponse,
  JobsOverlayResponse,
  RawSeriesResponse,
  SessionStatus,
  TensorRequest,
  TimeDomainResponse,
  ZScoresResponse,
} from "./types";

const BASE_URL = import.meta.env.VITE_API_BASE ?? "http://localhost:8010";

async function post<T>(path: string, body: unknown): Promise<T> {
  const resp = await fetch(`${BASE_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    const detail = await resp.text();
    throw new Error(`${path} failed (${resp.status}): ${detail}`);
  }
  return resp.json() as Promise<T>;
}

async function get<T>(path: string): Promise<T> {
  const resp = await fetch(`${BASE_URL}${path}`);
  if (!resp.ok) {
    const detail = await resp.text();
    throw new Error(`${path} failed (${resp.status}): ${detail}`);
  }
  return resp.json() as Promise<T>;
}

export const api = {
  createSession: (request: TensorRequest) =>
    post<{ session_id: string; status: string }>("/session/create", request),

  sessionStatus: (sessionId: string) => get<SessionStatus>(`/session/${sessionId}/status`),

  embedding: (sessionId: string, params: { n_neighbors: number; min_dist: number; random_state?: number }) =>
    post<EmbeddingResponse>("/inter/embedding", { session_id: sessionId, ...params }),

  clusters: (
    sessionId: string,
    k: number,
    umap: { n_neighbors: number; min_dist: number; random_state?: number },
  ) => post<ClustersResponse>("/inter/clusters", { session_id: sessionId, k, ...umap }),

  explain: (
    sessionId: string,
    k: number,
    umap: { n_neighbors: number; min_dist: number; random_state?: number },
  ) => post<ExplainResponse>("/inter/explain", { session_id: sessionId, k, ...umap }),

  timedomain: (
    sessionId: string,
    k: number,
    umap: { n_neighbors: number; min_dist: number; random_state?: number },
  ) => post<TimeDomainResponse>("/inter/timedomain", { session_id: sessionId, k, ...umap }),

  clusterMeans: (
    sessionId: string,
    k: number,
    umap: { n_neighbors: number; min_dist: number; random_state?: number },
    metrics: string[],
    smoothing_w: number,
  ) =>
    post<ClusterMeansResponse>("/inter/cluster_means", {
      session_id: sessionId,
      k,
      ...umap,
      metrics,
      smoothing_w,
    }),

  zscores: (
    sessionId: string,
    nodeIds: string[],
    metrics: string[],
    band: Band,
    baseline?: Record<string, [number, number]>,
  ) =>
    post<ZScoresResponse>("/intra/zscores", {
      session_id: sessionId,
      node_ids: nodeIds,
      metrics,
      band,
      baseline: baseline ?? null,
    }),

  baseline: (sessionId: string, metric: string, nodeIds: string[]) =>
    post<BaselineResponse>("/intra/baseline", { session_id: sessionId, metric, node_ids: nodeIds }),

  rawSeries: (sessionId: string, nodeIds: string[], metrics: string[], t0: number, t1: number) =>
    post<RawSeriesResponse>("/raw/series", { session_id: sessionId, node_ids: nodeIds, metrics, t0, t1 }),

  jobsOverlay: (sessionId: string, nodeIds: string[]) =>
    post<JobsOverlayResponse>("/jobs/overlay", { session_id: sessionId, node_ids: nodeIds }),
};
