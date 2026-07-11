"""Phase 8 item 5 (research track): these tests check the contrastive
pipeline runs correctly end-to-end and that the comparison harness produces
a well-formed verdict -- they do NOT assert the contrastive path wins,
since whether it should be adopted is exactly the open question this
module exists to answer (gated behind evidence, not assumed).
"""
from __future__ import annotations

import numpy as np

from evaluation.fixtures import planted_cluster_tensor
from evaluation.research_contrastive import run_contrastive_vs_multidr, train_contrastive


def test_train_contrastive_produces_valid_embedding_shape():
    X, _ = planted_cluster_tensor(n_per_group=6, n_groups=3, T=40)
    V = train_contrastive(X, embed_dim=8, epochs=20)
    assert V.shape == (18, 8)
    assert not np.isnan(V).any()
    # encoder L2-normalizes its output
    norms = np.linalg.norm(V, axis=1)
    np.testing.assert_allclose(norms, 1.0, atol=1e-5)


def test_train_contrastive_deterministic_given_seed():
    X, _ = planted_cluster_tensor(n_per_group=6, n_groups=3, T=40)
    V1 = train_contrastive(X, embed_dim=8, epochs=20, seed=7)
    V2 = train_contrastive(X, embed_dim=8, epochs=20, seed=7)
    np.testing.assert_allclose(V1, V2)


def test_run_contrastive_vs_multidr_produces_well_formed_verdict():
    X, true_labels = planted_cluster_tensor(n_per_group=10, n_groups=4, T=60)
    result = run_contrastive_vs_multidr(X, true_labels, k=4, embed_dim=16, epochs=100)

    for pipeline in ("contrastive", "multidr"):
        assert -1.0 <= result[pipeline]["ari"] <= 1.0
        assert "silhouette" in result[pipeline]
        assert "davies_bouldin" in result[pipeline]
        assert "calinski_harabasz" in result[pipeline]

    assert isinstance(result["adopt_recommendation"], bool)
    # documents the actual outcome at time of writing, for anyone reading
    # test output: MulTiDR's dr1 (explicit per-metric temporal PCA) versus a
    # generically-trained small encoder is not expected to favor adoption
    # without further tuning -- this is not asserted, just noted.
    print(f"\n[research_contrastive] adopt_recommendation={result['adopt_recommendation']}")
    print(f"[research_contrastive] contrastive={result['contrastive']}")
    print(f"[research_contrastive] multidr={result['multidr']}")
