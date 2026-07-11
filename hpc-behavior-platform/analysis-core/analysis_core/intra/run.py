"""CLI milestone for Phase 4: produce the metric x node z-score matrix for a
chosen cluster and band.

    python -m analysis_core.intra.run --start ... --end ... --resolution 60 \
        --k 4 --cluster 0 --band 2h
"""
from __future__ import annotations

import argparse
from datetime import datetime

import numpy as np

from analysis_core.inter.pipeline import InterClusterPipeline
from analysis_core.intra.zscores import compute_zscores


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Phase 4 intra-cluster z-score pipeline")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--resolution", type=int, default=60)
    parser.add_argument("--k", type=int, default=4)
    parser.add_argument("--cluster", type=int, default=0, help="which kmeans cluster to inspect")
    parser.add_argument("--band", default="2h", choices=["5m", "30m", "2h", "24h", "7d"])
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

    node_mask = labels == args.cluster
    node_idx = np.where(node_mask)[0]
    if len(node_idx) == 0:
        print(f"cluster {args.cluster} has no nodes (k={args.k})")
        return

    cluster_nodes = [bundle.nodes[i] for i in node_idx]
    tensor_by_metric = {
        metric: bundle.X[np.ix_(node_idx, [m_i])][:, 0, :]
        for m_i, metric in enumerate(bundle.metrics)
    }

    result = compute_zscores(tensor_by_metric, band=args.band, resolution_s=args.resolution)

    print(f"cluster {args.cluster}: {len(cluster_nodes)} nodes, band={args.band}")
    if result.degenerate_metrics:
        print(f"degenerate (no signal in this band): {result.degenerate_metrics}")
    print()
    header = "node".ljust(20) + "".join(m.ljust(14) for m in result.metrics)
    print(header)
    for row_i, node in enumerate(cluster_nodes):
        row = "".join(f"{result.z[row_i, m_i]:+.2f}".ljust(14) for m_i in range(len(result.metrics)))
        flag = "  <-- |z|>3" if np.any(np.abs(result.z[row_i]) > 3) else ""
        print(node.ljust(20) + row + flag)


if __name__ == "__main__":
    main()
