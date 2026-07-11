"""DR ablation (Phase 7 item 4, paper Fig. 9): compare PCA-only, UMAP-direct,
and t-SNE against the default MulTiDR pipeline on the same planted labels.

All three alternatives skip dr1 (the per-metric temporal PCA summarization)
and run directly on the flattened raw (N, M*T) tensor -- this tests whether
dr1's per-node z-scoring + temporal-PCA summarization is actually what gives
MulTiDR its edge, versus just being any-old 2-phase DR.
"""
from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.manifold import TSNE
from sklearn.metrics import adjusted_rand_score
import umap

from analysis_core.inter.quality import cluster_quality
from evaluation.quality_benchmark import run_multidr


def _flatten(X: np.ndarray) -> np.ndarray:
    n, m, t = X.shape
    return np.nan_to_num(X.reshape(n, m * t))


def _cluster(E: np.ndarray, k: int, random_state: int = 42) -> np.ndarray:
    return KMeans(n_clusters=k, random_state=random_state, n_init=10).fit_predict(E)


def run_ablation(X: np.ndarray, true_labels: np.ndarray, k: int, random_state: int = 42) -> dict[str, Any]:
    flat = _flatten(X)
    n = X.shape[0]

    results: dict[str, Any] = {}

    E_multidr, labels_multidr, _ = run_multidr(X, k, random_state=random_state)
    results["multidr"] = (E_multidr, labels_multidr)

    E_pca = PCA(n_components=2, random_state=random_state).fit_transform(flat)
    results["pca_only"] = (E_pca, _cluster(E_pca, k, random_state))

    n_neighbors = min(15, max(1, n - 1))
    E_umap = umap.UMAP(n_neighbors=n_neighbors, min_dist=0.1, n_components=2, random_state=random_state).fit_transform(flat)
    results["umap_direct"] = (E_umap, _cluster(E_umap, k, random_state))

    perplexity = min(30, max(2, n - 1))
    E_tsne = TSNE(n_components=2, random_state=random_state, perplexity=perplexity).fit_transform(flat)
    results["tsne"] = (E_tsne, _cluster(E_tsne, k, random_state))

    report = {}
    for method, (E, labels) in results.items():
        ari = float(adjusted_rand_score(true_labels, labels))
        quality = cluster_quality(E, labels)
        report[method] = {"ari": ari, **quality}
    return report


def write_markdown_report(report: dict[str, dict[str, float]], path: Path) -> None:
    lines = [
        "# DR Ablation (paper Fig. 9)",
        "",
        f"Generated: {datetime.datetime.now(datetime.timezone.utc).isoformat()}",
        "",
        "| method | ARI | silhouette | davies_bouldin | calinski_harabasz |",
        "|---|---|---|---|---|",
    ]
    order = ["multidr", "pca_only", "umap_direct", "tsne"]
    for method in order:
        r = report[method]
        lines.append(
            f"| {method} | {r['ari']:.3f} | {r['silhouette']:.3f} | {r['davies_bouldin']:.3f} | "
            f"{r['calinski_harabasz']:.1f} |"
        )
    path.write_text("\n".join(lines) + "\n")
