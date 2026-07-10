"""Contrastive PCA cluster explanation (paper Sec III-B-3), replacing v1's
deep contrastive/InfoNCE approach.

Direct implementation (option 2 from the v2 spec) rather than the author's
`ccpca` C++ package, to avoid a build-time dependency: for each cluster,
target = V[labels == c], background = V[labels != c]; the top eigenvector of
C(alpha) = cov(target) - alpha * cov(background) is the metric weight vector.

Automatic alpha selection: line-search over log-spaced alphas in [1e-2, 1e2],
picking the alpha whose top eigenvector maximizes a separation score
score(alpha) = |mean(target_proj) - mean(background_proj)| / (std(background_proj) + eps)
-- i.e. how many background standard deviations apart the two groups' means
are along that direction (a t-statistic-like discrepancy). This is the
"discrepancy between target/background projections" criterion referenced by
the spec; documented here since the ccPCA paper's own best-alpha search
criterion isn't reproduced verbatim.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

ALPHA_MIN = 1e-2
ALPHA_MAX = 1e2
N_ALPHAS = 40
EPS = 1e-8


@dataclass
class CCPCAResult:
    cluster: int
    weights: np.ndarray  # (M,) magnitude = importance, sign = direction
    ranked_metric_idx: np.ndarray  # metric indices sorted by |weight| desc
    alpha: float


def _best_alpha_direction(target: np.ndarray, background: np.ndarray) -> tuple[np.ndarray, float]:
    """Returns (unit weight vector w: (M,), chosen alpha).

    Both covariances are computed relative to the *combined* (target +
    background) mean rather than each group's own mean: np.cov's default
    per-group demeaning would silently erase exactly the signal we're
    looking for -- a cluster whose values sit at a different, tightly
    consistent level than the rest of the population (a location shift, not
    a variance-structure difference). Centering on a shared reference point
    makes that location shift show up as elevated "variance" in the target
    covariance, which is what the alpha-weighted eigendecomposition below is
    built to detect.
    """
    combined = np.concatenate([target, background], axis=0)
    global_mean = combined.mean(axis=0)
    target_c = target - global_mean
    background_c = background - global_mean

    C_t = (target_c.T @ target_c) / max(1, len(target_c) - 1)
    C_b = (background_c.T @ background_c) / max(1, len(background_c) - 1)
    C_t = np.atleast_2d(C_t)
    C_b = np.atleast_2d(C_b)

    alphas = np.logspace(np.log10(ALPHA_MIN), np.log10(ALPHA_MAX), N_ALPHAS)
    best_score = -np.inf
    best_w = np.zeros(C_t.shape[0])
    best_alpha = alphas[0]

    for alpha in alphas:
        C = C_t - alpha * C_b
        C = (C + C.T) / 2.0  # symmetrize for numerical stability
        eigvals, eigvecs = np.linalg.eigh(C)
        w = eigvecs[:, -1]  # eigenvector for the largest eigenvalue

        target_proj = target @ w
        background_proj = background @ w
        score = abs(target_proj.mean() - background_proj.mean()) / (background_proj.std() + EPS)

        if score > best_score:
            best_score = score
            best_w = w
            best_alpha = float(alpha)

    # orient sign so positive weight => higher values in the target cluster
    target_proj = target @ best_w
    background_proj = background @ best_w
    if target_proj.mean() < background_proj.mean():
        best_w = -best_w

    return best_w, best_alpha


def ccpca_explain(V: np.ndarray, labels: np.ndarray) -> list[CCPCAResult]:
    """V: (N, M) first-pass DR result. labels: (N,) cluster assignments.

    One-vs-rest per cluster: target = V[labels==c], background = V[labels!=c].
    Returns one CCPCAResult per unique cluster label, sorted by label value.
    """
    results = []
    for cluster in sorted(np.unique(labels)):
        mask = labels == cluster
        target = V[mask]
        background = V[~mask]

        if target.shape[0] < 2 or background.shape[0] < 2:
            weights = np.zeros(V.shape[1])
            alpha = float(ALPHA_MIN)
        else:
            weights, alpha = _best_alpha_direction(target, background)

        ranked = np.argsort(-np.abs(weights))
        results.append(
            CCPCAResult(cluster=int(cluster), weights=weights, ranked_metric_idx=ranked, alpha=alpha)
        )

    return results
