"""CLI milestone for Phase 3: fetch a tensor via tensor-store, run the
inter-cluster pipeline, print cluster sizes, quality metrics, and top-5
discriminative metrics per cluster.

    python -m analysis_core.inter.run --start ... --end ... --resolution 60 --k 4
"""
from __future__ import annotations

import argparse
from datetime import datetime

import numpy as np

from analysis_core.inter.pipeline import InterClusterPipeline
from analysis_core.inter.quality import cluster_quality, trustworthiness_continuity


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Phase 3 inter-cluster pipeline")
    parser.add_argument("--start", required=True, help="ISO datetime, e.g. 2026-01-01T00:00:00")
    parser.add_argument("--end", required=True, help="ISO datetime")
    parser.add_argument("--resolution", type=int, default=60, help="grid resolution in seconds")
    parser.add_argument("--k", type=int, default=4, help="number of clusters")
    parser.add_argument("--n-neighbors", type=int, default=15)
    parser.add_argument("--min-dist", type=float, default=0.1)
    parser.add_argument("--clickhouse-host", default="localhost")
    parser.add_argument("--clickhouse-port", type=int, default=8123)
    parser.add_argument("--clickhouse-password", default="devpass")
    args = parser.parse_args()

    from tensor_store.api import TensorRequest, get_tensor
    from tensor_store.loader import get_client

    client = get_client(
        host=args.clickhouse_host, port=args.clickhouse_port, password=args.clickhouse_password
    )
    request = TensorRequest(
        start=datetime.fromisoformat(args.start),
        end=datetime.fromisoformat(args.end),
        resolution_s=args.resolution,
    )
    bundle = get_tensor(request, client=client)

    pipeline = InterClusterPipeline(bundle.X)
    labels, _ = pipeline.get_labels(k=args.k, n_neighbors=args.n_neighbors, min_dist=args.min_dist)
    E = pipeline.get_E(n_neighbors=args.n_neighbors, min_dist=args.min_dist)
    V = pipeline.get_V()
    ccpca = pipeline.get_ccpca(k=args.k, n_neighbors=args.n_neighbors, min_dist=args.min_dist)

    quality = cluster_quality(E, labels)
    trust, continuity = trustworthiness_continuity(V, E)

    print(f"nodes={len(bundle.nodes)} metrics={len(bundle.metrics)} k={args.k}")
    print()
    print("cluster sizes:")
    for cluster in sorted(np.unique(labels)):
        print(f"  cluster {cluster}: {int((labels == cluster).sum())} nodes")
    print()
    print("quality metrics:")
    print(f"  silhouette:         {quality['silhouette']:.4f}")
    print(f"  davies_bouldin:     {quality['davies_bouldin']:.4f}")
    print(f"  calinski_harabasz:  {quality['calinski_harabasz']:.4f}")
    print(f"  trustworthiness:    {trust:.4f}")
    print(f"  continuity:         {continuity:.4f}")
    print()
    print("top-5 discriminative metrics per cluster:")
    for result in ccpca:
        top5 = result.ranked_metric_idx[:5]
        names = [bundle.metrics[i] for i in top5]
        print(f"  cluster {result.cluster} (alpha={result.alpha:.3g}): {names}")


if __name__ == "__main__":
    main()
