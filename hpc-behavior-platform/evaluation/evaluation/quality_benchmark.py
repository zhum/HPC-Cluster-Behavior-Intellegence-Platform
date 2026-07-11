"""Cluster quality benchmark (Phase 7 item 1): paper's Table I metric set
(silhouette, Davies-Bouldin, Calinski-Harabasz, trustworthiness, continuity)
plus the Phase 3 shipping gate (planted-cluster ARI > 0.9 and quality beats
a PCA-only baseline), written to a markdown report artifact per run.
"""
from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.metrics import adjusted_rand_score

from analysis_core.inter.clustering import kmeans_cluster
from analysis_core.inter.multidr import dr1_pca_over_time, dr2_umap
from analysis_core.inter.quality import cluster_quality, trustworthiness_continuity


def run_multidr(X: np.ndarray, k: int, random_state: int = 42) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    V = dr1_pca_over_time(X)
    n_neighbors = min(15, max(1, X.shape[0] - 1))
    E = dr2_umap(V, n_neighbors=n_neighbors, random_state=random_state)
    labels, _ = kmeans_cluster(E, k=k, random_state=random_state)
    return E, labels, V


def run_pca_only_baseline(X: np.ndarray, k: int, random_state: int = 42) -> tuple[np.ndarray, np.ndarray]:
    """Naive baseline: PCA(2) directly on the flattened raw (N, M*T) tensor,
    skipping dr1's per-node z-scoring entirely -- this is what the Phase 3/7
    gate ("quality metrics beat PCA-only baseline") is checking against.
    """
    n, m, t = X.shape
    flat = np.nan_to_num(X.reshape(n, m * t))
    E = PCA(n_components=2, random_state=random_state).fit_transform(flat)
    model = KMeans(n_clusters=k, random_state=random_state, n_init=10)
    labels = model.fit_predict(E)
    return E, labels


def benchmark_report(X: np.ndarray, true_labels: np.ndarray, k: int, dataset_name: str) -> dict[str, Any]:
    E_multidr, labels_multidr, V = run_multidr(X, k)
    E_pca, labels_pca = run_pca_only_baseline(X, k)

    ari_multidr = float(adjusted_rand_score(true_labels, labels_multidr))
    ari_pca = float(adjusted_rand_score(true_labels, labels_pca))
    q_multidr = cluster_quality(E_multidr, labels_multidr)
    q_pca = cluster_quality(E_pca, labels_pca)
    trust, cont = trustworthiness_continuity(V, E_multidr)

    return {
        "dataset": dataset_name,
        "n_nodes": X.shape[0],
        "n_metrics": X.shape[1],
        "n_timesteps": X.shape[2],
        "ari_multidr": ari_multidr,
        "ari_pca_only": ari_pca,
        "quality_multidr": q_multidr,
        "quality_pca_only": q_pca,
        "trustworthiness": trust,
        "continuity": cont,
        "gate_ari_pass": ari_multidr > 0.9,
        "gate_beats_pca_baseline": q_multidr["silhouette"] > q_pca["silhouette"],
    }


def write_markdown_report(results: list[dict[str, Any]], path: Path) -> None:
    lines = [
        "# Cluster Quality Benchmark",
        "",
        f"Generated: {datetime.datetime.now(datetime.timezone.utc).isoformat()}",
        "",
        "| dataset | N | M | T | ARI (MulTiDR) | ARI (PCA-only) | silhouette | davies_bouldin | "
        "calinski_harabasz | trustworthiness | continuity | gate: ARI>0.9 | gate: beats PCA-only |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        q = r["quality_multidr"]
        lines.append(
            f"| {r['dataset']} | {r['n_nodes']} | {r['n_metrics']} | {r['n_timesteps']} | "
            f"{r['ari_multidr']:.3f} | {r['ari_pca_only']:.3f} | {q['silhouette']:.3f} | "
            f"{q['davies_bouldin']:.3f} | {q['calinski_harabasz']:.1f} | {r['trustworthiness']:.3f} | "
            f"{r['continuity']:.3f} | {'PASS' if r['gate_ari_pass'] else 'FAIL'} | "
            f"{'PASS' if r['gate_beats_pca_baseline'] else 'FAIL'} |"
        )

    lines.append("")
    lines.append("## PCA-only baseline detail (for comparison)")
    lines.append("")
    lines.append("| dataset | silhouette | davies_bouldin | calinski_harabasz |")
    lines.append("|---|---|---|---|")
    for r in results:
        q = r["quality_pca_only"]
        lines.append(f"| {r['dataset']} | {q['silhouette']:.3f} | {q['davies_bouldin']:.3f} | {q['calinski_harabasz']:.1f} |")

    path.write_text("\n".join(lines) + "\n")
