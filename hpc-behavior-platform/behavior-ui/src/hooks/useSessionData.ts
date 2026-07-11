import { useEffect, useState } from "react";
import { api } from "../api/client";
import type {
  ClustersResponse,
  EmbeddingResponse,
  ExplainResponse,
  SessionStatus,
  TimeDomainResponse,
} from "../api/types";
import { useStore } from "../store/useStore";

/** Polls /session/{id}/status until ready or error. */
export function useSessionStatus(sessionId: string | null) {
  const [status, setStatus] = useState<SessionStatus | null>(null);

  useEffect(() => {
    if (!sessionId) {
      setStatus(null);
      return;
    }
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;

    async function poll() {
      try {
        const s = await api.sessionStatus(sessionId!);
        if (cancelled) return;
        setStatus(s);
        if (s.status === "pending") {
          timer = setTimeout(poll, 300);
        }
      } catch {
        if (!cancelled) timer = setTimeout(poll, 500);
      }
    }
    poll();

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [sessionId]);

  return status;
}

/** Embedding (E) refetches ONLY on session/umapParams change -- NOT on k,
 * which is the mechanism behind the <1s "change k without recomputing
 * UMAP" acceptance criterion: k only drives a separate /inter/clusters call.
 */
export function useEmbedding(sessionId: string | null, ready: boolean) {
  const umapParams = useStore((s) => s.umapParams);
  const [embedding, setEmbedding] = useState<EmbeddingResponse | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!sessionId || !ready) return;
    setLoading(true);
    api
      .embedding(sessionId, umapParams)
      .then(setEmbedding)
      .finally(() => setLoading(false));
  }, [sessionId, ready, umapParams.n_neighbors, umapParams.min_dist, umapParams.random_state]);

  return { embedding, loading };
}

export function useClusters(sessionId: string | null, ready: boolean) {
  const umapParams = useStore((s) => s.umapParams);
  const k = useStore((s) => s.k);
  const [clusters, setClusters] = useState<ClustersResponse | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!sessionId || !ready) return;
    setLoading(true);
    api
      .clusters(sessionId, k, umapParams)
      .then(setClusters)
      .finally(() => setLoading(false));
  }, [sessionId, ready, k, umapParams.n_neighbors, umapParams.min_dist, umapParams.random_state]);

  return { clusters, loading };
}

export function useExplain(sessionId: string | null, ready: boolean) {
  const umapParams = useStore((s) => s.umapParams);
  const k = useStore((s) => s.k);
  const [explain, setExplain] = useState<ExplainResponse | null>(null);

  useEffect(() => {
    if (!sessionId || !ready) return;
    api.explain(sessionId, k, umapParams).then(setExplain);
  }, [sessionId, ready, k, umapParams.n_neighbors, umapParams.min_dist, umapParams.random_state]);

  return explain;
}

export function useTimeDomain(sessionId: string | null, ready: boolean) {
  const umapParams = useStore((s) => s.umapParams);
  const k = useStore((s) => s.k);
  const [timedomain, setTimedomain] = useState<TimeDomainResponse | null>(null);

  useEffect(() => {
    if (!sessionId || !ready) return;
    api.timedomain(sessionId, k, umapParams).then(setTimedomain);
  }, [sessionId, ready, k, umapParams.n_neighbors, umapParams.min_dist, umapParams.random_state]);

  return timedomain;
}
