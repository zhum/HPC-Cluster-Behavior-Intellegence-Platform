"""Phase 8 item 5 (research track, gated behind evidence): deep contrastive
node embeddings as an ALTERNATIVE to dr1_pca_over_time -- this is where v1's
InfoNCE idea lives, explicitly NOT wired into analysis-core's production
pipeline. It is evaluated here against MulTiDR using the same Phase 7
harness (planted-cluster ARI + Table I quality metrics); adoption is gated
on that comparison actually favoring it, not assumed.

Encoder: a small MLP over a random time-crop of each node's per-metric
z-scored series (same z-scoring spirit as dr1: removes per-node offset/
scale so only shape differences carry signal). Trained with a SimCLR-style
NT-Xent / InfoNCE loss -- two augmented crops of the same node are the
positive pair, every other node in the batch is a negative.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from sklearn.metrics import adjusted_rand_score

from analysis_core.inter.clustering import kmeans_cluster
from analysis_core.inter.multidr import dr2_umap
from analysis_core.inter.quality import cluster_quality
from evaluation.quality_benchmark import run_multidr

DEFAULT_EMBED_DIM = 16
DEFAULT_EPOCHS = 200


class ContrastiveEncoder(nn.Module):
    def __init__(self, input_dim: int, embed_dim: int = DEFAULT_EMBED_DIM, hidden_dim: int = 64) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, embed_dim),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return F.normalize(self.net(x), dim=-1)


def _zscore_per_node(X: np.ndarray) -> np.ndarray:
    mean = np.nanmean(X, axis=2, keepdims=True)
    std = np.nanstd(X, axis=2, keepdims=True)
    std_safe = np.where(std == 0, 1.0, std)
    return np.nan_to_num((X - mean) / std_safe, nan=0.0)


def _augment(Xz: np.ndarray, rng: np.random.Generator, crop_len: int, noise_std: float = 0.1) -> np.ndarray:
    n, m, t = Xz.shape
    start = int(rng.integers(0, t - crop_len + 1))
    cropped = Xz[:, :, start : start + crop_len]
    noisy = cropped + rng.normal(0, noise_std, size=cropped.shape)
    return noisy.reshape(n, m * crop_len)


def _center_crop(Xz: np.ndarray, crop_len: int) -> np.ndarray:
    n, m, t = Xz.shape
    start = (t - crop_len) // 2
    return Xz[:, :, start : start + crop_len].reshape(n, m * crop_len)


def _info_nce_loss(z: torch.Tensor, n: int, temperature: float) -> torch.Tensor:
    """z: (2n, D) L2-normalized embeddings, rows [0:n)=view1, [n:2n)=view2.
    Positive pair for row i is n+i (mod 2n); every other row is a negative.
    """
    sim = z @ z.T / temperature
    sim.fill_diagonal_(-1e9)
    targets = torch.cat([torch.arange(n, 2 * n), torch.arange(0, n)])
    return F.cross_entropy(sim, targets)


def train_contrastive(
    X: np.ndarray,
    embed_dim: int = DEFAULT_EMBED_DIM,
    epochs: int = DEFAULT_EPOCHS,
    lr: float = 1e-3,
    temperature: float = 0.5,
    crop_fraction: float = 0.8,
    seed: int = 42,
) -> np.ndarray:
    """X: (N, M, T) -> V: (N, embed_dim), the contrastive analog of dr1's
    (N, M) PCA-over-time output -- feed it through the same dr2_umap +
    kmeans_cluster path used for MulTiDR for a fair comparison.
    """
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    n, m, t = X.shape
    crop_len = max(4, int(t * crop_fraction))

    Xz = _zscore_per_node(X)
    encoder = ContrastiveEncoder(input_dim=m * crop_len, embed_dim=embed_dim)
    optimizer = torch.optim.Adam(encoder.parameters(), lr=lr)

    for _ in range(epochs):
        view1 = _augment(Xz, rng, crop_len)
        view2 = _augment(Xz, rng, crop_len)
        batch = torch.tensor(np.concatenate([view1, view2], axis=0), dtype=torch.float32)

        optimizer.zero_grad()
        z = encoder(batch)
        loss = _info_nce_loss(z, n, temperature)
        loss.backward()
        optimizer.step()

    with torch.no_grad():
        final = torch.tensor(_center_crop(Xz, crop_len), dtype=torch.float32)
        V = encoder(final).numpy()
    return V


def run_contrastive_vs_multidr(
    X: np.ndarray,
    true_labels: np.ndarray,
    k: int,
    embed_dim: int = DEFAULT_EMBED_DIM,
    epochs: int = DEFAULT_EPOCHS,
    random_state: int = 42,
) -> dict[str, Any]:
    """Head-to-head comparison on the same (X, true_labels): contrastive
    embedding -> dr2_umap -> kmeans, vs. the full MulTiDR pipeline. Returns
    ARI + Table I quality metrics for both, plus an explicit
    adopt_recommendation gate: only True if the contrastive path beats
    MulTiDR on BOTH cluster recovery (ARI) and quality (silhouette).
    """
    n_neighbors = min(15, max(1, X.shape[0] - 1))

    V_contrastive = train_contrastive(X, embed_dim=embed_dim, epochs=epochs, seed=random_state)
    E_contrastive = dr2_umap(V_contrastive, n_neighbors=n_neighbors, random_state=random_state)
    labels_contrastive, _ = kmeans_cluster(E_contrastive, k=k, random_state=random_state)

    E_multidr, labels_multidr, _ = run_multidr(X, k, random_state=random_state)

    ari_contrastive = float(adjusted_rand_score(true_labels, labels_contrastive))
    ari_multidr = float(adjusted_rand_score(true_labels, labels_multidr))
    q_contrastive = cluster_quality(E_contrastive, labels_contrastive)
    q_multidr = cluster_quality(E_multidr, labels_multidr)

    adopt = ari_contrastive > ari_multidr and q_contrastive["silhouette"] > q_multidr["silhouette"]

    return {
        "contrastive": {"ari": ari_contrastive, **q_contrastive},
        "multidr": {"ari": ari_multidr, **q_multidr},
        "adopt_recommendation": adopt,
    }


def write_markdown_report(result: dict[str, Any], path) -> None:
    c, m = result["contrastive"], result["multidr"]
    verdict = "ADOPT" if result["adopt_recommendation"] else "DO NOT ADOPT (MulTiDR remains the default)"
    lines = [
        "# Research Track: Deep Contrastive Embeddings vs. MulTiDR",
        "",
        "Phase 8 item 5 -- gated behind evidence. This is NOT wired into the",
        "production pipeline; adoption depends solely on the table below.",
        "",
        "| pipeline | ARI | silhouette | davies_bouldin | calinski_harabasz |",
        "|---|---|---|---|---|",
        f"| contrastive (InfoNCE) | {c['ari']:.3f} | {c['silhouette']:.3f} | {c['davies_bouldin']:.3f} | {c['calinski_harabasz']:.1f} |",
        f"| MulTiDR (default) | {m['ari']:.3f} | {m['silhouette']:.3f} | {m['davies_bouldin']:.3f} | {m['calinski_harabasz']:.1f} |",
        "",
        f"**Verdict: {verdict}**",
    ]
    path.write_text("\n".join(lines) + "\n")
